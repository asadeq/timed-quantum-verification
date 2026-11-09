# Soundness note — spot-check keys are forgeable (found 2026-11-08)

**Status: open. Not fixed by the bitmap removal; tracked as a follow-up design task.**

## Finding

`submitAndVerify` accepts a claim whose spot-check keys are fabricated. Empirical
probe (temporary forge test, since removed):

1. Build the honest K=8 claim for the fixture solver (`gen_fixtures.build_claim`).
2. Keep the real tables and Merkle paths; replace each spot check's `k_l`, `k_r`
   with random 16-byte values and set `k_o = table[a][b] ⊕ pad(k_l, k_r, gi)`.
3. Register the honest puzzle root, submit → **contract returns `Verified`**.

## Why

The Yao equation `k_o == table[a][b] ⊕ pad(k_l, k_r, gi)` is locally satisfiable
by construction: the solver supplies all three of `k_l`, `k_r`, `k_o`, so any
random key pair yields a consistent `k_o`. The garbled tables are in the clear in
the puzzle body `Z` (which the solver holds), so the forger can also rebuild the
whole Merkle tree and produce valid paths for any leaf. The GL check is equally
unconstrained: pick any `y`, set `s_claim := gf2(r, y) ⊕ r·m⊕s` (both `r` and
`r·m⊕s` are public in `Z`).

So a forger holding `Z` wins with probability **1**, not 2^-K as documented in
`BENCHMARK_PLAN.md` and the `SpotCheck.sol` header. The on-chain checks verify
*internal consistency* of the claim, not that the solver did the T sequential
steps.

## Candidate fixes

- **Seal the tables** (preferred direction): encrypt each non-reusable gate's
  garbled table under the chain state so the *decrypted* table is only
  recoverable by doing the T steps, and commit the decrypted table in the
  Merkle leaf. The forger then cannot present any valid leaf (preimage
  resistance) and is caught at the Merkle check with probability 1.
- Commit the gate-parentage (chain topology) in the header and have the
  contract verify key chaining (`k_o(gi) == k_parent(gj)`), so fabricated keys
  cannot chain from the handed input keys.
- Contract-driven spot-check selection alone does **not** help: fabrication
  works for any gate.

## Repro

See the probe description above; the exact recipe is 6 lines of Python on top of
`gen_fixtures.build_claim` (fabricate keys, re-serialize, register, submit).
