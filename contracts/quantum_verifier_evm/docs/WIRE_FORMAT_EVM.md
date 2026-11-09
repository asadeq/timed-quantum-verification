# EVM claim wire format (v1)

The claim submitted to `QuantumVerifier.submitAndVerify(uint32, bytes)` is
**packed, not ABI-encoded** — ABI struct encoding would add offset/length words
and 32-byte padding to every field, roughly tripling the calldata, and calldata
is ~77% of the verification bill (see
[`ETHEREUM_SERVICE.md`](../../ETHEREUM_SERVICE.md)).

All integers are big-endian. This is the format produced by
`python/gen_fixtures.py::serialize_claim` and decoded by
`src/lib/ClaimCodec.sol`.

```
u32            r_len
bytes          r                      (Goldreich-Levin mask)
u8             r_dot_m_xor_s          (0 or 1; >1 rejected)
u32            header_path_count
(bytes32,u8)[] header_path            (sibling, is_left)
u32            K                      (spot-check count)
SpotCheck[K] {
    u32            gate_index
    bytes16        k_l
    bytes16        k_r
    bytes16        k_o
    bytes16[4]     table              (row-major (a,b)=(00,01,10,11))
    u32            path_count
    (bytes32,u8)[] path               (sibling, is_left)
}
u32            y_len
bytes          y                      (circuit output bits, LSB-first)
u8             s_claim                (0 or 1; >1 rejected)
```

## Merkle tree

Built off-chain by the puzzle generator; only the root (`puzzleHash`) is
registered on-chain.

```
header leaf   = SHA-256( r || r_dot_m_xor_s_be32 || solver_be20 )
gate leaf(gi) = SHA-256( table[gi]_4x16B || gi_be32 )
internal      = SHA-256( left || right )   (odd count: last pairs with itself)
```

`solver_be20` is the submitting account's address, so a claim only verifies
from the account it was built for — with a bounty attached, an observed
transaction cannot be front-run to steal the payout.

The tree contains a leaf **only for non-reusable gates**, so a valid gate-leaf
Merkle proof is itself the non-reusability proof — the claim carries no
non-reusable gate list (the Soroban format's `u32[]`, or the earlier EVM
bitmap, are gone). This makes the claim size constant in T: only the gate
*indices* move with T, and they live inside fixed-width fields.

Path entry `(sibling, is_left)`: `is_left = 1` means the sibling is the LEFT
child (the current node is the right child); the path byte must be 0 or 1.

## Differences from the Soroban format ([SPEC.md](../../SPEC.md))

| Field | Soroban | EVM | Why |
|---|---|---|---|
| non-reusable gates | `u32[]` (2,564 B for 640 gates) | **not carried** | the tree only has non-reusable leaves, so the gate-leaf Merkle proof is the membership proof; claim size is constant in T |
| `r_dot_m_xor_s` | u32 | u8 | it is a bit |
| `s_claim` | u32 | u8 | it is a bit |
| `y_bits` | `u32[]` of bits | raw bytes | 112 B saved |
| header leaf | `SHA-256(r ‖ flag ‖ list)` | `SHA-256(r ‖ flag ‖ solver)` | binds the claim to the submitting account (anti-front-running for escrowed bounties) |

**Consequence:** the header leaf differs, so `puzzle_hash` differs from the
Soroban one. Compute each chain's hash off-chain and register it on that chain.
The claim bytes differ anyway (`scval` vs packed calldata).

## Bounty settlement (EVM only)

`registerPuzzle` is **permissionless**: anyone can register a puzzle root and
escrow a `uint96 bounty` in the payment token (native ETH or ERC-20); the
caller becomes the puzzle's `owner`, the only party that can `reclaimBounty`.
The first `submitAndVerify` whose claim passes all checks pays the bounty to
`msg.sender` in the same transaction (`BountyPaid` event, `claimedBy`
recorded) and re-verifications are rejected with reason 5. A bounty of `0`
keeps the verify-only semantics: honest claims verify any number of times.

Money map (the commerce flow):

```
client  --escrow bounty--> contract --pay on verified claim--> server
client  --feePerVerify*--> contract --withdraw--> admin        (*optional; 0 = free mode)
server  --gas (linear in K)--> chain, win or lose
```

The header leaf binds the submitting account, so the client must know the
solver's address when computing the root it registers — registration commits
to a (puzzle, solver) pair, and no bystander can divert the payout.
`experiment_commerce.py` runs this loop end-to-end with distinct
client/server/attacker accounts and records a balance-accounted ledger to
`bench/commerce_ledger.json`; `plot_commerce.py` renders
`bench/figures/commerce_profit.png`.

### Service pricing: the server quotes, the client escrows

The bounty is the service price, and it has two legs: the estimated
verification gas (a pass-through the client covers at cost, priced from the
measured gas model) and the **server's margin** — the labor price for the
sequential `PSolve` work. Only the server knows what that labor is worth, so
the server publishes it to the standalone
[`FeeQuoteRegistry`](../../src/FeeQuoteRegistry.sol)
(`setQuote(marginWei)` / `quoteOf(server)`), and the client reads the quote
before escrowing:

```
server  --setQuote(marginWei)--> FeeQuoteRegistry
client  --quoteOf(server)------> registry                (price discovery)
client  --registerPuzzle(root, bounty = gasLeg + quote)--> QuantumVerifier
server  --bounty >= quote? --yes--> submitAndVerify -> paid atomically
                           --no--> refuse (no work); client reclaimBounty
```

The quote is discovery, not enforcement: the bounty pays whatever was
escrowed, and the server's acceptance stays implicit (it checks the bounty
against its quote before submitting and simply refuses if underpaid —
escrow-before-work is what makes that refusal safe). The margin is quoted flat
(the server's labor scales with T, not K — K only drives the reimbursed gas
leg); a per-T quote is the natural v2. `experiment_commerce.py --quote-from
<registry>` reads the quote; without it, the legacy client-side `--margin-usd`
guess applies.

**The pricing window** (`experiment_pricing.py`, rendered as
`pricing_window.png`): sweeping a bounty multiplier λ over the fair price
shows the two-sided constraint. Below the server's reservation
(λ < 1) the market does not clear — measured refusals, client reclaims. Above
it the server's net rises linearly — but so does the forger's incentive
`2^-K·B − gas`: the minimum safe K for a bounty of λ·B is
`K_req = log2(λ·B/gas)`, which crosses the client's chosen K at
`λ* = 2^K·gas/B`. Measured on Base Sepolia at K=8 (B ≈ $0.504, forger gas ≈
$0.0057): **λ\* = 2.90** — pay less than fair and no server serves you; pay
more than ~2.9× and your own generosity makes the bounty worth attacking. On
L1 at 30 gwei the same formula gives λ\* ≈ 251: on an expensive chain the gas,
not the bounty, deters forgery.

## Canonical decoding rules (anti-malleability)

The decoder (`Cursor` + `ClaimCodec`) enforces, and a claim that violates any of
these reverts before any cryptographic check runs:

- every read is bounds-checked (`Truncated`), including inside `assembly`;
- booleans are canonical: path `is_left` and both committed bits must be 0 or 1;
- the claim region must be consumed exactly (`TrailingBytes`);
- caller-controlled lengths are capped: `r`/`y` ≤ 64 B, K ≤ 64,
  path depth ≤ 64;
- `r` and `y` must have equal length (the Rust port silently truncated — that
  would let a solver choose how much of `r` is checked).

## Measured sizes and gas

Fixture: `lam = msg_bits = 128`, T = 1, 640 non-reusable gates, Merkle depth 10.
Claim size is constant in T (3,980 B at K=8 for T = 1…100).

| K | claim bytes | verify gas (gasleft probe, forge test) |
|---|---|---|
| 1 | 830 | 112,736 |
| 8 | 3,980 | 320,842 |

Measured T=1 vs T=100 at K=8: 321,130 vs 320,986 — flat (Δ 0.04%; the old
bitmap-header format drifted +26% over the same range). Reject paths cost less
(they bail out early).
