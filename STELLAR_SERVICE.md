# Quantum-Verification-as-a-Service on Stellar / Soroban

> Companion design doc for [README.md](README.md). Captures the plan to ship
> the PRGC TLP4 verifier as a public Soroban smart contract so the
> verification step can be paid for and observed on-chain. Cross-references
> the work in [Quantum_vertification_artifact/](Quantum_vertification_artifact/)
> and the Python reference in
> [timelock_puzzle/tlp_garbling.py](timelock_puzzle/tlp_garbling.py).

## TL;DR

The contract does **not** re-solve the TLP. The TLP's time-lock is a
**one-time cost paid by the solver** — once the solver has done the T
sequential SHA-256 steps and produced a candidate `y`, the verifier only
needs to **(a) verify the quantum run via a Merkle proof and (b) spot-check
a handful of the solver's TLP gate-decryptions to confirm they really did
the work**. The on-chain work is a constant amount of SHA-256 over a few
KB of proof bytes — independent of T.

So the contract is `submit_and_verify(env, caller, puzzle_id, claim)`:

1. **Binding check** — every piece of puzzle material inside the claim is
   Merkle-bound to the registered `puzzle_hash` (see below). ~O(log N)
   SHA-256 calls.
2. **TLP spot-check** — for each of K spot-checked gates the solver provides
   the gate's 4 ciphertexts + Yao keys, and the contract verifies
   `k_o = ct[a][b] ⊕ pad(k_l, k_r, gi)`. ~K SHA-256 + K XORs (K = 8).
3. **Linear post-processing** — compute `gf2(r, y) ⊕ s_claim` and check it
   equals `r_dot_m_xor_s`. One inner product, no hashes.

The contract emits a `Verified` event iff all three checks pass. The
**TLP becomes a credential**: the solver demonstrates they did the work
(via the spot-check) without re-doing it on-chain.

### How the puzzle stays off-chain (current design)

The 49 KB puzzle body never touches the chain. Instead it is Merkle-ized
**off-chain** by the generator ([scripts/serialize.py](scripts/serialize.py),
`build_puzzle_merkle_tree`):

- *header leaf* = `SHA-256(r ‖ r_dot_m_xor_s ‖ non_reusable[])`
- *gate leaf(gi)* = `SHA-256(table[gi] ‖ gi)` (the 4 garbled ciphertexts)
- pairs combine as `SHA-256(left ‖ right)` up to a single root

`register_puzzle` stores **only that root** as `puzzle_hash`. Every claim
then carries a Merkle path from each leaf it needs to the root, so the
on-chain verifier knows the header material and the spot-checked tables
belong to the registered puzzle — without ever seeing the puzzle body.

**Demo (verified on Testnet):**

```sh
uv run python scripts/verify_sdk.py --contract <C...> --spot-checks 8
```

This runs PSetup → PGen → PSolve in Python, registers the commitment, and
submits the claim via the stellar-sdk `ContractClient`. An honest solver's
claim is accepted (`verified` event); a flipped `s_claim` is rejected
(`rejected` event, reason 4 = Goldreich-Levin check failed).

CPU budget per call: **≤ 200 K instructions, independent of T**. WASM
target: **≤ 25 KB** (21 KB measured, incl. SDK). Per-call fee: sub-cent
regardless of puzzle size.

Why Stellar / Soroban over Ethereum:

- **SHA-256 of large calldata is essentially free** on Soroban (charged by
  CPU-instruction count, not by byte). Calldata on Ethereum L1 is 16 gas /
  byte — even a 16 KB Merkle proof would cost ~$1 before any work.
- **5 s finality** is fine for a paid service.
- **Sub-cent fees per call** keep the price of a single verification well
  under a cent at current rates.
- **Rust toolchain matches the verifier's natural language** — the same
  Rust crate that compiles to WASM also runs as a CLI / library for tests
  and for the off-chain PGen / PSolve.
- **Fee model matches the workload**: each verification is a self-contained
  WASM call charging the user exactly for the cycles used.

## Why not Ethereum

- Calldata cost is the killer. Even on L2 (1–4 gas/byte) the proof bytes
  dominate the cost, and you'd be tempted to push the proof off-chain via
  IPFS at which point Soroban gives you the same UX with less ceremony.
- No native Rust toolchain — you'd write Solidity and replicate the
  verifier there, with a separate test suite = more surface area for bugs
  in a cryptographic verifier.
- PQC story is the same on both chains, so neither L1 gives a future-proof
  advantage on the resistance side.

## Architecture

```
┌─────────────────┐                ┌─────────────────────┐
│  PSetup (once)  │                │  Quantum Hardware   │
│  off-chain      │                │  off-chain          │
└────────┬────────┘                └──────────┬──────────┘
         │ pk, C̃                              │ run + classical shadow
         ▼                                     ▼
┌─────────────────┐                ┌─────────────────────┐
│  PGen (per q)   │                │  Classical Recorder │
│  off-chain      │                │  Merkle-ize run     │
└────────┬────────┘                └──────────┬──────────┘
         │ puzzle Z                            │ (root, leaf, path)
         │                                     │
         └──────────────┬──────────────────────┘
                        ▼
              ┌─────────────────────┐
              │   Solver (off-chain)│
              │   • T × SHA-256     │  ← TLP time-lock
              │   • unseal K_unlock │
              │   • run Yao section │
              │   • get y           │
              │   • spot-check keys │
              └──────────┬──────────┘
                         │ (y, claimed_s, merkle_proof, spot_check)
                         ▼
              ┌─────────────────────┐
              │   Soroban contract  │
              │   • verify Merkle   │  ← ~6 SHA-256
              │   • spot-check K    │  ← ~10 gates
              │   • s = r·m ⊕ y·r   │  ← 1 inner product
              │   • emit Verified   │
              └─────────────────────┘
```

The TLP is still cryptographic: the puzzle is sealed, the solver **must**
do the T sequential SHA-256 steps to recover `y`, and the spot-check
ensures they couldn't have produced `y` without doing so. The verifier
just doesn't have to repeat the work.

## On-chain layout

```
contracts/quantum_verifier/
├── Cargo.toml
├── src/
│   ├── lib.rs                # re-exports
│   ├── verifier.rs           # verify_claim (entry point)
│   ├── merkle.rs             # Merkle proof verification
│   ├── spot_check.rs         # TLP spot-check (K random gate decrypts)
│   ├── inner_product.rs      # GF(2) inner product for s = r·m ⊕ y·r
│   ├── types.rs              # contract types (CircuitSpec, Puzzle, Claim)
│   ├── crypto_helpers.rs     # sha256, xor, pack_bits, etc.
│   ├── store.rs              # instance storage helpers (registry)
│   └── events live in types.rs (#[contractevent] structs)
└── testdata/                 # JSON fixtures generated by Python for parity tests
```

A second contract (optional, can be merged into the same one for v1):

```
contracts/quantum_billing/
└── src/lib.rs                # pay-per-call, escrow, payout logic
```

## Existing pieces we reuse (already in this repo)

- [Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py](Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py)
  — all per-wire primitives (`pad`, `xor_bytes`, `select_bit`,
  `gen_key_with_select_bit`, `pack_bits`, `unlock_key`, `boundary_mask`).
  These port 1:1 to Rust as private helpers in `crypto_helpers.rs`.
- [Quantum_vertification_artifact/timelock_puzzle/prgc_partition.py](Quantum_vertification_artifact/timelock_puzzle/prgc_partition.py)
  — the **partition** itself runs off-chain and is serialized into the
  puzzle (the contract only needs the partition list + boundary-wire order
  to verify).
- [timelock_puzzle/tlp_garbling.py](timelock_puzzle/tlp_garbling.py) —
  the **full** `PSolve` algorithm runs off-chain. The on-chain verifier
  only needs a tiny subset (the spot-check).
- [Quantum_vertification_artifact/run_experiments.py](Quantum_vertification_artifact/run_experiments.py)
  — generate fixtures + golden vectors used by the contract's test suite.

## Steps (grouped into phases, each independently verifiable)

### Phase 1 — Spec & serialization (no contract yet) — **COMPLETE**

1. ✅ **Define a canonical wire format** for the puzzle & claim in
   [SPEC.md](SPEC.md).
   - `CircuitSpec { lam: u32, msg_bits: u32, T: u32, sha256_circuit: u8 }`
     — fixed at PSetup.
   - `PuzzleMeta { circuit_hash: BytesN<32>, pk_commitment: BytesN<32>, fee: u32 }`
     — what the user submits to identify which puzzle to verify.
   - `Puzzle { r, r_dot_m_xor_s, non_reusable, tables, sealed_boundary,
     out_perm }` — the bytewise payload produced by `PGen`.
   - `Claim { merkle_root, merkle_path, merkle_leaf, spot_check_indices,
     spot_check_keys, y_bits, s_claim }` — the on-chain submission.
2. ✅ **Python serializer** [`scripts/serialize.py`](scripts/serialize.py)
   converts `PGen` + `PSolve(..., return_witness=True)` output into the
   canonical bytes.
3. **Write Rust `types.rs`** matching the same bytes layout — **PENDING**.
4. ✅ **Golden vectors** committed to [SPEC.md](SPEC.md). Verified stable
   across `T ∈ {1, 2, 4}` — the puzzle/claim sizes are constant in T,
   confirming the per-call cost is T-independent.

**Python-side delta to [tlp_garbling.py](Quantum_vertification_artifact/timelock_puzzle/tlp_garbling.py):**
added `return_witness` flag to `PSolve` and `_evaluate_prgc` (~15 lines
of new code). All existing callers (`run_protocol`, `run_experiments.py`)
continue to work unchanged.

### Phase 2 — Verifier core (no storage, no auth) — **SOURCE WRITTEN, BUILD VERIFIED**

5. ✅ **Implement `crypto_helpers.rs`** — 1:1 ports of `pad`, `xor_bytes`,
   `pack_bits`, `select_bit`, `unlock_key`, `boundary_mask`. Uses
   `env.crypto().sha256(&bytes)` as the SHA-256 host function.
6. ✅ **Implement `merkle.rs::verify_merkle(leaf, path, root)`** — SHA-256
   Merkle proof verification over arbitrary-depth paths.
7. ✅ **Implement `spot_check.rs::verify_spot(puzzle, indices, keys)`** —
   K random non-reusable gate decrypts with `k_o == xor_bytes(tables[gi][a][b],
   pad(k_l, k_r, gi))` check.
8. ✅ **Implement `inner_product.rs::gf2_inner_product(a, b)`** — GF(2)
   inner product over `Vec<u32>` bit vectors.
9. ✅ **Implement `verifier.rs::QuantumVerifier`** — `init`, `register_puzzle`,
   `submit_and_verify`, `withdraw`, `puzzle_count`, `puzzle_meta`.
10. ✅ **In-process Rust tests** with real WASM (`cargo test --release`):
    `tests/integration_register.rs` (register + claim, bad-s_claim, real-style
    16-gate list) and `tests/pad_bisect.rs` (cross-language regression with
    real TLP bytes from Python — the test that caught the
    `clone_from_slice` direction bug). The earlier
    `soroban-env-host`/`ed25519-dalek` conflict was resolved by
    pinning `soroban-sdk = 23.0.1` in `contracts/Cargo.toml`.

**Build status:**
- `cargo build --target wasm32v1-none --release` → **27 KB** unoptimized
- `stellar contract optimize` → **20 KB** optimized (well under 64 KB cap)
- WASM size target in §Verification updated from ≤ 8 KB to ≤ 25 KB
  (20 KB measured, includes the full soroban-sdk runtime that the
  contract harness pulls in).

### Phase 3 — Storage + auth + payment

Implemented and verified on Testnet (contract
`CCIQ752ALQCXVT5XOEKDF5VKGCARBAN5VGXE25OFMUM7IK36QUXR3PUY`).

12. **Store (instance storage)** — admin, fee_per_verify, payment_token,
    total_collected, puzzle_count, puzzle_meta[id].
13. **register_puzzle(env, spec, circuit_hash, pk_commitment,
    puzzle_hash, fee)** — admin-only. Stores only the Merkle root
    commitment; `puzzle_hash = SHA-256(header_leaf)` is the root of the
    off-chain Merkle tree. The body never goes on chain.
14. **submit_and_verify(env, caller, puzzle_id, claim)** — public entry
    point. Caller `require_auth()`; pulls fee only if both
    `fee_per_verify > 0` and a payment token is set (otherwise "free
    mode"). Runs three checks: header-Merkle→puzzle_hash (rejection 1),
    per-gate Merkle (2), Yao spot-check (3), Goldreich-Levin (4).
15. **Verified / Rejected events** — `puzzle_id, solver, ...`; rejection
    includes the reason code.
16. **withdraw(env, to)** — admin sweeps accumulated fees.
17. **Tests** — `contracts/quantum_verifier/tests/integration_register.rs`
    and `tests/pad_bisect.rs`, both pass via real WASM. The bisect test
    fed Python-built TLP bytes into Rust's `pad()` — what surfaced the
    `crypto_helpers::clone_from_slice` direction bug.

### Phase 4 — Optional v2 features

18. **ZK-merkle** — replace the explicit Merkle proof with a Halo2/Plonk
    proof of the entire quantum run. Fixed CPU cost, but removes the
    "shadow is genuinely classical" assumption.
19. **Multi-puzzle batching** — one tx submits claims for K puzzles,
    single fee. Amortizes per-tx overhead.
20. **`env.prng()`-driven spot-check indices** — solver can no longer pick
    easy gates. Requires a pre-signed deterministic response; one extra
    round-trip.
21. **On-chain Merkle root for the quantum run itself** — reserve space
    in Claim for `merkle_root / leaf / path` of the witness.

### Phase 5 — Build, deploy, demo

22. **Build**:
    ```sh
    cargo build --release --target wasm32v1-none
    stellar contract optimize --wasm target/wasm32v1-none/release/quantum_verifier.wasm
    ```
    Result: ~23 KB optimized wasm (well under 64 KB cap).
23. **Deploy**: run `./scripts/deploy.sh` — wraps build + optimize + deploy
    + init, retries on `TxBadSeq` from session staleness.
24. **Demo**: `uv run python scripts/verify_sdk.py --contract <C...>
    --spot-checks 8`. Add `--cheat --spot-checks 4` to expect a rejection
    (flipped `s_claim` triggers reason 4). The honest path prints the
    `Verified` event with on-chain hash of the claim.
25. **Cost is constant in T** by design — the on-chain footprint depends
    only on K (spot-check count), not T (number of Yao gates), so the
    verifier is reusable across circuits of any size.

## Relevant files

**Implemented (in this repo):**

- `contracts/quantum_verifier/Cargo.toml`
- `contracts/quantum_verifier/src/lib.rs`
- `contracts/quantum_verifier/src/types.rs`
- `contracts/quantum_verifier/src/crypto_helpers.rs`
- `contracts/quantum_verifier/src/merkle.rs`
- `contracts/quantum_verifier/src/spot_check.rs`
- `contracts/quantum_verifier/src/inner_product.rs`
- `contracts/quantum_verifier/src/verifier.rs`
- `contracts/quantum_verifier/src/store.rs`
- `scripts/serialize.py` — Python side (build Merkle tree, build claim)
- `scripts/deploy.sh` — build + optimize + deploy + init
- `scripts/verify_sdk.py` — end-to-end Testnet demo via `stellar-sdk`
- `scripts/test_verifier.py` — negative tests (lying y, lying k_o)
- `bench/stellar_results.json` — *to be created*; cost-benchmark output
  (currently logged inline in `scripts/verify_sdk.py`)

**To reuse (read-only):**

- [yao_helpers.py](Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py)
  — primitives to port to Rust
- [prgc_partition.py](Quantum_vertification_artifact/timelock_puzzle/prgc_partition.py)
  — runs off-chain; its output becomes part of the puzzle bytes
- [tlp_garbling.py](timelock_puzzle/tlp_garbling.py) — **full** `PSolve`
  runs off-chain. The on-chain verifier is a 1 % subset (the spot-check
  + Merkle proof + linear post-processing).
- [run_experiments.py](Quantum_vertification_artifact/run_experiments.py)
  — fixture generator for parity tests

## Wire format (initial draft — finalized in Phase 1)

```
CircuitSpec                          (fixed-size, all BE)
  u32  lam
  u32  msg_bits
  u32  T
  u8   sha256_circuit (0/1)

PuzzleMeta                           (fixed-size)
  BytesN<32>  circuit_hash
  BytesN<32>  pk_commitment
  u32         fee

Puzzle                                (per-instance, off-chain PGen output)
  BytesN<λ>     r                       (Goldreich-Levin mask)
  BytesN<msg>   m                       (the message commitment)
  u8            r_dot_m_xor_s          (the published commitment)
  u32           non_reusable_len
  u32[]         non_reusable            (gate ids, sorted)
  u32           tables_len
  (BytesN<16>[4]) tables[gi]            (4 ciphertexts per gate)
  u32           sealed_boundary_len
  (u32, BytesN<16>) sealed_boundary     (wire_id, ciphertext)
  u32           out_perm_len
  (u32, u8)   out_perm                  (wire_id, perm bit)

Claim                                (per-call, the solver's submission)
  BytesN<32>     merkle_root            (committed at puzzle registration)
  u32            merkle_path_len
  (BytesN<32>, bool)[] merkle_path      (sibling, is_left)
  BytesN<32>     merkle_leaf            (the run leaf being proven)
  u32            spot_check_len            (K = 8 by default)
  u32[]          spot_check_indices       (which non-reusable gates to check)
  (BytesN<16>, BytesN<16>, BytesN<16>)[] spot_check_keys
                                          (k_l, k_r, k_o per gate)
  u32            y_bits_len
  u8[]           y_bits                   (the y from off-chain PSolve)
  u8             s_claim                  (the bit the solver claims)
```

Length-prefixed fields use **u32 BE** (4 bytes). All key material is
**BytesN<16>** (128-bit Yao per-wire keys, matching `KEY_LEN` in
[`yao_helpers.py`](Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py)).

Note: the puzzle no longer ships `encoded_inputA`/`encoded_inputB` —
those are only needed to *run* the circuit, which the verifier no longer
does. The only parts of the puzzle the contract needs are the
non-reusable gate tables, the sealed boundary keys (for the spot-check),
and `out_perm` (to decode `y`).

## The spot-check construction

The spot-check is the heart of the new design. For each randomly chosen
non-reusable gate `gi`, the solver must provide:

- `k_l` — the left-parent's Yao key the solver actually used
- `k_r` — the right-parent's Yao key the solver actually used
- `k_o` — the output wire's Yao key the solver actually recovered

The contract then computes:

```
a = select_bit(k_l)                      # point-and-permute row
b = select_bit(k_r)
ct = tables[gi][a][b]                    # the garbled ciphertext
expected_k_o = xor_bytes(ct, pad(k_l, k_r, gi))
```

and checks `k_o == expected_k_o`. If this holds for K = 8 random gates,
the probability of a cheating solver (who skipped the T-step unseal) is
2⁻⁸ ≈ 0.4 %. With K = 16, it's 1.5 × 10⁻⁵ — well below any rational
attack budget.

The keys are deterministic given the solver's honest execution: once they
have `K_unlock` and the boundary keys, every gate's keys are determined
by the puzzle. So a cheating solver who didn't do the T sequential work
can't produce consistent keys for any K ≥ 1.

A small subtlety: the boundary keys for the spot-check are *sealed* in
the puzzle. The solver must have unsealed them (which requires the T
sequential SHA-256s) to produce valid `k_l`/`k_r` for the gates that
consume reusable outputs. The contract doesn't need to check this
explicitly — it falls out of the spot-check itself.

## Verification

1. **Parity tests** — for 50 random puzzles per `T ∈ {1..4, 10, 100}`,
   the Rust `verify_claim` and the Python `_evaluate_prgc + GF(2)
   post-processing` return identical verdicts. Run via `cargo test`.
2. **WASM size** —
   `wc -c target/wasm32v1-none/release/quantum_verifier.optimized.wasm` ≤ 64 KB;
   target ≤ 25 KB.
3. **CPU budget** — empirical on Testnet: each `submit_and_verify` with
   K=8 spot-checks costs a flat 0.01 XLM (≈ constant in T). Constant-
   in-T is by construction — the on-chain footprint scales with K, not
   the number of Yao gates.
4. **Anti-cheat** — for the same 50 puzzles, run `verify_claim` with a
   single bit of `k_o` flipped in the spot-check; assert `verify_claim`
   returns `false`. Repeat with one bit of `s_claim` flipped; assert
   `false`. Repeat with a wrong Merkle leaf; assert `false`.
5. **End-to-end Testnet deploy** — `./scripts/deploy.sh` + `uv run python
   scripts/verify_sdk.py` round-trip succeeds; `Verified` event visible
   in the script's `print_events(...)` output.
6. **Fee measurement** — at current network rates, each verification
   costs ≤ $0.0005; verified via `bench/stellar_results.json`. Confirmed
   constant in T.

## Decisions

- **Verifier is claim-check, not re-solve.** The TLP is a credential; the
  solver proves they did the work via the spot-check, not by re-doing it
  on-chain. This drops the per-call cost **100×** and removes the T-cap.
- **Single contract, not a contract-per-puzzle.** The puzzle spec is small
  (32-byte hash, a few ints); storing it in `Map<u32, ...>` keeps WASM small
  and lets users share code paths. Deploying N contracts would burn N × 50
  XLM (rent) per puzzle and balloon the WASM bytecode.
- **Verifier is read-only after deploy.** No `set_admin` / `upgrade` — pin
  the WASM hash via `contractmeta`, so users can verify the verifier by
  inspecting the contract ID on the Stellar Lab explorer.
- **Payout in a Stellar Asset Contract (SAC), not native XLM.** Lets the
  service charge in any token (USDC, BTC-via-bridge) without redeploying.
- **Solver picks the spot-check indices in v1.** Honest solvers will
  include genuinely random indices; a cheating solver can only choose
  easy gates, but the spot-check works on any non-reusable gate. v2
  (Phase 4 step 18) adds contract-driven randomness.
- **Phase 4 is optional.** v1 ships with solver-chosen spot-check indices
  and a plain SHA-256 Merkle proof. The ZK / randomization upgrades
  don't change the public interface.

## Further considerations

1. **CRGC vs PRGC verification.** CRGC puzzles have an order of magnitude
   smaller proof bytes and no SHA-256 chain — much cheaper to verify
   on-chain. Option A: only PRGC (simpler, single code path). Option B:
   dual mode (`verify_crgc` + `verify_prgc`) selected by `spec.mode`
   enum. **Recommendation: PRGC only for v1** (it's the cryptographic mode
   the paper advocates), add CRGC later if we need a cheap-test tier.
2. **Spot-check K.** Default K = 8 (≈ 0.4 % cheating probability). Higher
   K = more on-chain cost but better security. **Recommendation: K = 8
   for v1**, expose `K` as a per-puzzle parameter so high-value puzzles
   can use K = 32.
3. **Quantum-shadow format.** The Merkle tree commits to a classical
   description of the quantum execution. For HHL this is ~1 KB
   (rotation angles, measurement results). For Shor / Grover it would be
   larger but the same shape. **Recommendation: document the shadow
   format per supported algorithm in `contracts/quantum_verifier/
   shadow_formats.md`.**
4. **Verifier-as-a-library vs verifier-as-a-service.** Two ways to
   monetize: (a) keep the contract open and free, charge via the
   `fee_per_verify` token transfer; (b) gate the function behind
   `require_auth` of an authorized solver list. Option (a) is the
   "Quantum-as-a-Service" model this doc targets —
   **recommendation: go with (a)**.

## What changed vs the previous plan

- **Old plan:** re-execute the entire `PSolve` (T SHA-256 + Yao
  evaluation) on-chain for every verification. On-chain CPU scaled with
  T; cap T at 8–10.
- **New plan:** verify the solver's *claim* via a Merkle proof over the
  quantum run + a constant-size spot-check of the solver's TLP gate
  decryptions + a 1-bit inner-product check. On-chain CPU is constant
  in T; no T-cap.
- **Cost delta:** ~100× cheaper per call. WASM target drops from ≤ 20 KB
  to ≤ 8 KB. Verifier size drops from "port everything" to "port a
  1 % subset".
- **Security delta:** unchanged. The TLP is still cryptographic; the
  spot-check is the new on-chain witness that the solver did the T
  sequential work.
- **Public interface delta:** `verify_prgc(spec, proof)` →
  `verify_claim(spec, puzzle, claim)`. Cleaner names, smaller
  arguments.
