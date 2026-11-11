# Soundness note — spot-check keys are forgeable (found 2026-11-08)

**Status: PARTIALLY FIXED (2026-11-10). The payout is now gated on the puzzle
secret; the spot-check forgery itself remains open but is no longer
payout-relevant.**

## Finding

`submitAndVerify` accepted a claim whose spot-check keys are fabricated. Empirical
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

So a forger holding `Z` won with probability **1**, not 2^-K as documented in
`BENCHMARK_PLAN.md` and the `SpotCheck.sol` header. The on-chain checks verified
*internal consistency* of the claim, not that the solver did the T sequential
steps.

## Fix applied: the secret commitment in the header leaf

The client knows the puzzle's embedded secret at setup (`PGen` samples `m`;
exposed as `tlp.embedded_message`). Registration now binds
`d = SHA-256(y ‖ s_claim ‖ r)` into the header leaf:

```
header leaf = SHA-256( r ‖ r_dot_m_xor_s ‖ d ‖ solver )
```

and `submitAndVerify` recomputes `d` from the claim's own `(y, s_claim, r)`
fields before the leaf check. Consequences (verified by probe + fixtures):

- **Wrong output with a coset-consistent `s_claim`** — the pair the GL parity
  alone would accept — now **rejects** (reason 1). Fixture `bad_y_consistent_s`.
- **A forger without the witness** cannot fill `(y, s_claim)` at all: `m` is
  sealed behind the PRGC keys and the boundary chain, so preimaging `d`
  requires solving the puzzle. **The payout now requires the sequential work.**
- **Fabricated spot-check keys with the honest `(y, s_claim)`** still verify —
  reframed: such a claim carries the true secret, i.e. the solver *has* the
  witness and did the work; the keys are not the payout gate. The spot-check
  forgery remains open as a hardening item (see candidate fixes below) but no
  longer affects payout soundness.
- The GL parity check is retained as defense-in-depth; it is subsumed by the
  leaf commitment (reason 4 is unreachable for well-formed claims — tampered
  claims exit at reason 1 first).

## Candidate fixes for the spot-check forgery itself (optional hardening)

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

The original probe recipe is 6 lines of Python on top of
`gen_fixtures.build_claim` (fabricate keys, re-serialize, register, submit).
Post-fix, the same probe still returns `Verified` (witness-holder case, see
above); the wrong-y probe returns `Rejected` reason 1.
