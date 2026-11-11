# Figures

Captions and interpretation for the figures in [`bench/figures/`](../bench/figures).
The images themselves carry data only — axis labels, tick labels and legends.
Everything explanatory lives here. Every panel is its own image file
(`figNa_…` / `figNb_…`); the prose below refers to them as panel (a)/(b) of
figure N.

## Scope

All figures are a **proof of concept**. Current quantum algorithms are
theoretically better than their classical counterparts but are still executed
on small, error-prone toy circuits, so the protocol is benchmarked at
640-gate garbled circuits with `T ≤ 100`. That is enough to exercise every
mechanism end to end — garble, seal, time-lock solve, claim, on-chain verdict,
escrow and payout — but it is **not** a production scale claim. Where a figure
extends beyond the measured range it is drawn dashed and is labelled as an
extrapolation.

Every number comes from measured runs against the escrow contract on Base
Sepolia (the latest sessions in
[`bench/evm_results.json`](../bench/evm_results.json): per-transaction gas, fee
and latency) and [`bench/commerce_ledger.json`](../bench/commerce_ledger.json)
(escrow cycles, balances, profit). Claim sizes in Figure 1b are
replayed from the real TLP rather than modelled. Fees are quoted at
ETH = $3,000.

Per-spot-check cost is ~29.5 k gas and the fixed cost ~71.7 k gas (incl. the
secret-commitment check), so the `K = 8` configuration used throughout costs
~308 k gas to verify.

---

## Figure 1 — `fig1a_gas_vs_T.png` + `fig1b_claim_bytes_vs_T.png`

![Gas composition vs T](../bench/figures/fig1a_gas_vs_T.png)

![On-chain bytes per claim vs T](../bench/figures/fig1b_claim_bytes_vs_T.png)

**(a) Gas composition vs T.** Verification gas at `K = 8` for
`T ∈ {1, 10, 25, 50, 100}`, split into the part that does not depend on `T`
(grey: operations, Merkle paths, Goldreich–Levin; blue: the eight Yao
spot-checks). Both segments are constant by construction and confirmed constant
by measurement: the `K`-linear model `gas = 71,673 + 29,537·K` predicts the
measured totals within 0.1 % at every `T`, so no third segment is drawn — the
former T-dependent term (the non-reusable-gate bitmap header) was removed from
the wire format: the puzzle tree contains a leaf only for non-reusable gates,
so the gate-leaf Merkle proof is the membership proof.

**(b) On-chain bytes per claim vs T.** The claim is a constant 3,980 B at
every `T`; `max_gate` still moves with `T` (895 → 13,567) but lives inside
fixed-width fields. The registered commitment stays 32 B. The puzzle
body — 641 Merkle leaves, ~44 kB of gate tables — never reaches the chain.
Nothing in the claim moves with `T`: the nine Merkle paths (3,006 B), the eight
spot-check tables (512 B) and the remaining fields (462 B) are byte-identical at
every `T`.

**Reading.** Both the verification *logic* and the claim *bytes* are constant
in `T`: bigger `T` means more off-chain solver work (PSolve grows linearly),
never a bigger on-chain check. There is no claim-size cap to worry about — the
former 4,096-byte bitmap limit is gone with the bitmap itself.

---

## Figure 2 — `fig2a_gas_vs_K.png` + `fig2b_fee_vs_K.png`

![Gas and false-claim probability vs K](../bench/figures/fig2a_gas_vs_K.png)

![Fee per verification vs K](../bench/figures/fig2b_fee_vs_K.png)

**(a) Gas and false-claim probability vs K.** Gas for
`K ∈ {1, 2, 4, 8, 16}` at `T = 1` (left axis), against the probability `2^-K`
that a false claim survives all spot-checks (right axis). Gas is linear:
101,402 → 544,384, i.e. +29,537 per check.

**(b) Fee per verification vs K.** The same measured gas priced at four base
fees: an L2 at 0.05 gwei (Base/Arbitrum), and L1 at 1, 5 and 30 gwei. Black
crosses are the fees actually paid during the Base Sepolia sweeps (base fee
~0.004 gwei, so they sit on the L2 curve); the dashed line is the $0.50 server
margin used in the commerce experiment.

**Reading.** `K` is the security dial and it is cheap in gas terms: sixteen
spot-checks cost 1.8× eight (5.5× one), and in absolute terms the fee is
dominated by the venue, not by `K`. At `K = 8` the fee is $0.05 on an L2, $0.92 at 1 gwei,
$4.59 at 5 gwei and $27.55 at 30 gwei. The margin line matters: above it the chain costs
more per claim than the server earns, which happens at `K ≥ 8` on L1 at 5 gwei.

---

## Figure 3 — `fig3a_ev_vs_K.png` + `fig3b_payment_split.png`

![Expected value per claim vs K](../bench/figures/fig3a_ev_vs_K.png)

![Split of the client's payment](../bench/figures/fig3b_payment_split.png)

**(a) Expected value per claim vs K.** The honest server's payoff (it keeps the
$0.50 margin) against a forger's per-attempt expected value
`2^-K·B − gas`, for the four venues. Symmetric log scale, because the values
span four orders of magnitude.

**(b) Split of the client's payment.** The same `K = 8` payment decomposed into
the server's margin and the chain's fee, as a share of what the client pays.

**Reading.** On an L2 the forger's EV is still positive at `K = 1`
(+$0.24) and only breaks even near `K = 4` (+$0.005); the first `K` that
actually loses money is 8 (−$0.04). On L1 the gas cost alone makes forgery
unprofitable at every `K` (−$0.92 at 1 gwei, −$4.60 at 5 gwei, −$27.61 at
30 gwei at `K = 8`) — the forger pays the same calldata price for a rejected
claim as for an accepted one. The corollary is panel (b): the cheaper the
chain, the larger the share of the client's money that reaches the server
(92 % on an L2 versus 2 % on L1 at 30 gwei).

---

## Figure 4 — `fig4a_verdict_time_vs_T.png` + `fig4b_offchain_phases_vs_T.png`

![Time to a trusted verdict vs T](../bench/figures/fig4a_verdict_time_vs_T.png)

![Off-chain phases vs T](../bench/figures/fig4b_offchain_phases_vs_T.png)

**(a) Wall-clock to a trusted verdict vs T.** Two ways for a client to obtain a
verdict it believes: re-run the protocol itself, or read the on-chain verdict.
The self-recompute cost is `1.70 ms + 33.1 µs per sequential step`, fitted from
the measured `T = 1 … 100` range (dots, median of 5 solves per point) and drawn
dashed beyond it. The on-chain cost is one block — median ~2.0 s on Base
Sepolia (2 s blocks) — which is independent of `T`. The open marker is the
crossing point.

**(b) Off-chain phases vs T.** What the server actually spends: `PSetup`
(garble and seal) is linear in `T`, 11.4 ms → 111.4 ms; `PGen` is roughly flat
at 8.4–11.0 ms; `PSolve` (producing the answer) is 1.8 ms → 5.1 ms.

**Reading.** The two curves in (a) cross at `T ≈ 60,000`. Below that, checking
the claim locally is faster than waiting for a block; above it, the sequential
work dominates and the on-chain check is the only practical option. At the
toy scale used here the crossing is far to the right — this is the honest
consequence of `T ≤ 100` and is why the figure is the PoC's statement of intent
rather than its measurement: a production time-lock is many orders of magnitude
larger, while the on-chain curve stays flat in `T`. Panel (b) gives the
complementary economic point — the server is selling sequential work that the
client cannot skip without also giving up the ability to check the result.

---

## Figure 5 — `fig5_security_map.png`

![Minimum K vs base fee](../bench/figures/fig5_security_map.png)

Minimum integer `K` for which a forger's expected value
`2^-K·B − gas` is non-positive, swept over base fees from 0.001 to 100 gwei at
a fixed $0.50 margin. Shaded region: forgery is profitable. Markers: the four
venues of Figures 2 and 3.

**Reading.** With `B = fee + margin` the condition simplifies to
`K* = ⌈log₂(1 + margin/fee)⌉`, so the security requirement is set by the ratio
of the server's margin to the verification fee. An L2 needs `K ≥ 5`, L1 at
1 gwei needs `K ≥ 2`, and at 5 gwei or above the gas cost alone is enough
(`K ≥ 1`). The practical consequence for a service that prices in dollars is
that an expensive chain is also a cheap one to secure — but it charges the
client far more for the privilege (Figure 3b), so the operating point is
`K` on a cheap chain versus `K = 1` on an expensive one.

---

## Figure 6 — `fig6_rejection_paths.png`

![Every branch of submitAndVerify](../bench/figures/fig6_rejection_paths.png)

Gas per attempt for the three measured branches of `submitAndVerify` at
K = 8 on Base Sepolia (current contract): the honest claim (Verified, 308k),
the lying solver (Rejected, reason 1 — the header leaf's secret commitment
`d = SHA-256(y ‖ s_claim ‖ r)` mismatches, 177k), and the unknown puzzle
(Rejected, reason 0 — the earliest exit, 177k).

**Reading.** The contract's decision tree is visible in gas terms: a tampered
claim exits at the secret-commitment check — *before* the expensive
spot-check phase — so rejection costs ~42 % less than honesty. The forger's
cheap rejection is the flip side of the payout gate: the bounty pays only
claims carrying the true embedded secret, and the forger cannot even reach
the spot-check phase. This is the "how the contract behaves" complement to
the economics figures: every branch is measured, not asserted.

---

## Bounty-cost assumption and sensitivity

Figures 2b, 3a, 3b and 5 price the bounty as `fee + margin` with the margin
**assumed USD 0.50** — the server's published `FeeQuoteRegistry` quote at
benchmark time; each of those titles states the assumption. The margin is the
dynamic quantity (the server can re-quote at any time), so
`bounty_sensitivity.tex` / `bounty_sensitivity.png` tabulate the outcomes per
quoted margin at K = 8: the client's bounty and the forger's EV on an L2
(0.05 gwei) and on L1 (30 gwei), and the minimum safe K per venue. Reading:
on the L2 the margin is the security dial (K\* rises 3 → 6 over
$0.10 → $2.00 and the forger's EV stays negative but approaches zero); on L1
the gas dominates at every margin (K\* = 1, EV ≈ −$27.5).

## Supporting material

The main argument is Figures 1–6 plus the commerce demo
(`commerce_profit_vs_T.png`, `commerce_ev_vs_K.png`) and the pricing-window demo
(`pricing_service_vs_lambda.png`, `pricing_security_vs_lambda.png`: the
measured server-net step at the reservation price, and the bounty's attack
incentive — the operating window [1, λ\*] where service is available and the
bounty is not worth attacking at the chosen K). The bounty's margin now comes
from the server's published
quote (`FeeQuoteRegistry`), not a client-side guess. The former
diagnostic figures (`honest_metrics`, `latency_sweeps`, `fee_volatility`,
`sepolia_metrics`, `constant_cost`, `sepolia_constant_cost`, `frontier`) and
their generators (`plot_results.py`, `plot_sepolia.py`) are archived under
`bench/figures/archive/` and `python/archive/` — they rendered working
diagnostics that made the underlying denominators auditable, and are kept for
reproducibility but are not part of the figure set.

## Regenerating

```sh
cd contracts/quantum_verifier_evm
uv run python python/plot_paper.py        # fig1a..fig6 + bounty_sensitivity
uv run python python/plot_commerce.py     # commerce_profit.png + pricing_window.png
```

## Known data issues

- Off-chain timings (`PSolve`, `PSetup`, `PGen`) are medians of 5 solves per
  point (`--solve-repeat 5`); single-shot timings are noisy enough to move the
  Figure 4a crossover by tens of thousands of steps.
- Anvil and live chains disagree on the early-exit paths (rejected claims) by
  more than the honest-path difference, so venues are never mixed in one gas
  series; every figure uses the latest session per point from a single venue
  (Base Sepolia).
