# QuantumVerifier (EVM)

Solidity port of the Soroban quantum verifier in
[`contracts/quantum_verifier`](../../contracts/quantum_verifier). Same claim
semantics, same four rejection reasons, different cost model. Design rationale
in [`ETHEREUM_SERVICE.md`](../../ETHEREUM_SERVICE.md).

## Layout

```
src/
  QuantumVerifier.sol          entry point: registerPuzzle / submitAndVerify /
                               reclaimBounty (escrowed bounties settle atomically)
  lib/Cursor.sol               bounds-checked packed-format decoder
  lib/ClaimCodec.sol           claim wire format + non-reusable bitmap
  lib/Merkle.sol               SHA-256 Merkle path verification
  lib/SpotCheck.sol            Yao gate-decryption spot-check
  lib/InnerProduct.sol         GF(2) byte-wise inner product (GL check)
  lib/SafeERC20.sol            fee transfer that tolerates odd tokens
  utils/ReentrancyGuard.sol    single-slot guard for withdraw / submit
python/
  gen_fixtures.py              real TLP -> Solidity test fixtures + pad vectors
test/
  fixtures/GeneratedFixtures.sol   (generated; placeholder until run)
script/Deploy.s.sol
```

## Quick start

```sh
cd contracts/quantum_verifier_evm
forge install foundry-rs/forge-std     # once
uv run python python/gen_fixtures.py   # generate fixtures from a real TLP run
forge test -vvv
```

## Full demo (local chain, no real funds)

```sh
export PATH="$HOME/.foundry/bin:$PATH"   # foundryup must be on PATH
cd contracts/quantum_verifier_evm
uv run python python/demo_eth.py --spot-checks 8
```

## Commerce experiment (client escrows, server profits)

The full service loop with three distinct parties — client registers a puzzle
and escrows a bounty, server solves the time-lock and claims it atomically,
attacker exercises every failure path:

```sh
uv run python python/experiment_commerce.py --t 1 --k 8            # happy path + attacks
uv run python python/experiment_commerce.py --sweep-t 1,10,25,50,100 --k 8
uv run python python/experiment_commerce.py --sweep-k 1,2,4,8,16 --t 1
uv run python python/plot_commerce.py                              # -> bench/figures/commerce_profit.png
```

Ledger lands in `bench/commerce_ledger.json`. Live run (three funded cast
keystores): add `--rpc-url $ETH_SEPOLIA_RPC --accounts CLIENT SERVER ATTACKER`.

## Paper figures

`plot_paper.py` renders the five figures of the proof-of-concept argument
(640-gate circuits, `T <= 100`, measured on Sepolia). The images carry data
only; captions, interpretation and the known data caveats are in
[docs/FIGURES.md](docs/FIGURES.md).

```sh
uv run python python/plot_paper.py        # -> bench/figures/fig{1..5}_*.png
```

| figure | |
|---|---|
| `fig1_flat_in_T.png` | gas composition and on-chain bytes per claim vs `T` |
| `fig2_linear_in_K.png` | gas and false-claim probability, and fee per verification vs `K` |
| `fig3_payoff.png` | expected value per claim, and the split of the client's payment |
| `fig4_why_chain.png` | time to a trusted verdict vs `T`; off-chain phase costs |
| `fig5_security_map.png` | minimum `K` for a non-positive forger EV vs base fee |

This is the EVM counterpart of `scripts/verify_sdk.py`. It runs PSetup → PGen →
PSolve off-chain, starts Anvil, deploys the verifier in free mode, registers the
puzzle commitment, and submits three claims:

```
==> 5a. submitAndVerify — honest solver (K=8)
   -> VERIFIED (s = 1)
==> 5b. submitAndVerify — lying solver (s_claim flipped)
   -> REJECTED (reason 4 = Goldreich-Levin check failed)
==> 5c. submitAndVerify — unknown puzzle id (999)
   -> REJECTED (reason 0 = puzzle not registered)
```

The puzzle body never touches the chain; only the Merkle root (112-byte bitmap
header) and the ~4 KB claim do. Options: `--T`, `--lam`, `--msg-bits`,
`--spot-checks`, `--port`.

## Wire format

Same packed layout as the Soroban claim, with two deliberate changes — both
optimisations, documented in `docs/WIRE_FORMAT_EVM.md`:

1. **non-reusable gates are a bitmap, not a `u32[]`** — saves ~2.5 KB (≈99 K gas)
   on the 640-gate TLP, and makes membership O(1) instead of O(K×N).
2. **`r_dot_m_xor_s` / `s_claim` are bytes, not u32** — they're bits.

The bitmap changes the header leaf, so `puzzle_hash` differs from the Soroban
one. Compute each chain's hash off-chain and register it on that chain.

## Deliberate improvements over the Rust version

- **O(1) bitmap membership** replaces the O(K×N) `position()` scan (~50 K gas).
- **Strict length matching** in the GL check — Rust silently truncated `r`/`y`
  to the shorter one; here a mismatch reverts.
- **Canonical booleans** — path `is_left` bytes > 1 are rejected, preventing
  two distinct claim byte strings from producing the same verdict.
- **Full cursor consumption required** — trailing bytes are rejected.
- **No duplicated `pad()` computation** (Rust had a copy-paste artifact).
- **Merkle path built by index, not by value** in the Python tree generator —
  the Soroban `path_for_v2` could emit a spurious element on a hash collision.
- **Fee modes are unambiguous** — `paymentToken == address(0)` means native ETH;
  the old "fee > 0 but no token" combination silently meant free.
- **`MAX_PUZZLE_FEE` guard** catches unit mistakes before they reach users.
- **Zero dependencies** (no OpenZeppelin) — the verifier is auditable as a
  closed set of files.

## Cost expectation (K=8, 640 gates)

| term | gas |
|---|---|
| calldata (6.5 KB bitmap claim) | ~200 K |
| SHA-256 (header leaf + 8 gate paths + pads) | ~10 K |
| decoder + XOR + GL | ~15 K |
| **total per verification** | **~225–275 K** |

vs ~350 K for a claim that keeps the u32 gate list.
