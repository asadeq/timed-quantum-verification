#!/usr/bin/env python3
"""
Paper figures - proof-of-concept economics of settling PV-CVQC claims on a
smart contract.

Scope, stated on every figure: 640-gate garbled circuits, T <= 100, real
Sepolia runs against the escrow contract (evm_results.json +
commerce_ledger.json). Anything to the right of the measured T range in fig4 is
an extrapolation from the measured per-step cost and is drawn dashed.

  fig1_flat_in_T.png     (a) gas decomposed: fixed logic vs spot checks
                         (b) bytes the chain actually receives, per claim
  fig2_linear_in_K.png   (a) gas vs K, with 2^-K
                         (b) fee in USD vs K at named venue gas prices
  fig3_payoff.png        (a) cheat EV vs K in USD, per venue
                         (b) where the client's dollar goes, per venue
  fig4_why_chain.png     (a) wall-clock to obtain a trusted verdict vs T
                         (b) what the server pays off-chain, vs T
  fig5_security_map.png  minimum K for economic security vs gas price

Deliberately caption-free: axis labels, legends and short in-plot notes only.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent
REPO_ROOT = EVM_ROOT.parent.parent
FIG = EVM_ROOT / "bench" / "figures"

ETH_USD = 3000.0
MARGIN_USD = 0.50  # experiment_commerce.py --margin-usd default, fixed per claim

# Named venues. The PoC is chain-agnostic; the same bytecode priced at these
# base fees is the choice a deployer actually faces.
VENUES = [
    (0.05, "L2 @ 0.05 gwei", "#007d79"),
    (1.0, "L1 @ 1 gwei", "#0f62fe"),
    (5.0, "L1 @ 5 gwei", "#a56eff"),
    (30.0, "L1 @ 30 gwei", "#31135e"),
]

GAS = "#0f62fe"      # on-chain gas / crypto
FIXED = "#8d8d8d"    # K- and T-independent part
FEE = "#198038"      # money
SOLVE = "#e8a33d"
LAT = "#6929c4"
CHEAT = "#da1e28"

def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(True, alpha=0.25, lw=0.5)


def poc_note(fig):
    fig.text(0.5, 0.005, POC_NOTE, ha="center", fontsize=7, color="#6f6f6f")


# ---------------------------------------------------------------------------
# data access
# ---------------------------------------------------------------------------

def _sepolia(sessions, key, fixed):
    for s in sessions:
        # Both Ethereum Sepolia and Base Sepolia sessions qualify; sessions are
        # in file order and honest_rows keeps the latest per key value, so
        # newer (current wire-format) sessions take precedence over
        # pre-bitmap-removal ones.
        if not s.get("venue", "").endswith("sepolia"):
            continue
        p = s.get("params", {})
        if key not in p or any(p.get(k) != v for k, v in fixed.items()):
            continue
        yield s


def honest_rows(sessions, key, fixed):
    """Latest sepolia session per `key` value -> mean honest-run stats."""
    out = {}
    for s in _sepolia(sessions, key, fixed):
        v = s["params"][key]
        runs = [r for r in s["runs"] if r["name"].startswith("verify_honest")]
        if not runs:
            continue
        n = len(runs)
        o = s.get("offchain_ms", {})
        out[v] = {
            "gas": sum(r["gas_used"] for r in runs) / n,
            "fee_eth": sum(r["gas_used"] * r["effective_gas_price_wei"] for r in runs) / n / 1e18,
            "price_gwei": sum(r["effective_gas_price_wei"] for r in runs) / n / 1e9,
            "psetup_ms": o.get("psetup_garble_ms", float("nan")),
            "pgen_ms": o.get("pgen_ms", float("nan")),
            "psolve_ms": o.get("psolve_ms", float("nan")),
            "psolve_n": o.get("psolve_ms_n", 1),
        }
    return out


def latency_stats(sessions, key, fixed):
    """Median + IQR of time-to-receipt, from the latest session per `key`
    value. Pooling across sessions would mix venues with very different block
    times (~20 s Ethereum Sepolia vs ~2 s Base Sepolia)."""
    latest = {}
    for s in _sepolia(sessions, key, fixed):
        latest[s["params"][key]] = s
    groups = defaultdict(list)
    for v, s in latest.items():
        groups[v] += [
            r["latency_ms"] for r in s["runs"] if r["name"].startswith("verify_honest")
        ]
    out = {}
    for v, xs in groups.items():
        xs = sorted(xs)
        n = len(xs)
        out[v] = {
            "n": n,
            "med": statistics.median(xs) / 1000.0,
            "lo": xs[max(0, int(0.25 * (n - 1)))] / 1000.0,
            "hi": xs[min(n - 1, int(0.75 * (n - 1)))] / 1000.0,
        }
    return out


def claim_sizes(ts):
    """Claim byte sizes per T, built from the real TLP.

    Sizes are deterministic (only the gate *indices* move with T) and constant
    in T since the non-reusable gate list was dropped from the claim, so this
    is a faithful replay rather than a model.
    """
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "Quantum_vertification_artifact"))
    import gen_fixtures as G  # noqa: E402
    from timelock_puzzle.tlp_garbling import PythonGarbledTLP  # noqa: E402

    solver = bytes(20)
    out = {}
    for t in ts:
        tlp = PythonGarbledTLP(lam=128, message_size=128, T=t,
                               use_sha256=False, garbling_mode="prgc")
        pp = tlp.PSetup_Garble()
        z = tlp.PGen(1, pp)
        s, y, w = tlp.PSolve(z, pp, return_witness=True)
        nr = sorted(w["gate_keys"].keys())
        commitment = G.puzzle_commitment(y, s, z[1])
        _root, _levels, _nr = G._puzzle_tree(z, solver, commitment)
        claim = G.build_claim(tlp, z, w, s, y, nr[:8], solver=solver,
                              commitment=commitment)
        out[t] = {"claim": len(G.serialize_claim(claim)),
                  "max_gate": max(nr)}
    return out


# ---------------------------------------------------------------------------
# economics
# ---------------------------------------------------------------------------

def fee_usd(gas, gwei):
    """USD cost of `gas` units at a base fee of `gwei`."""
    return gas * gwei * 1e9 / 1e18 * ETH_USD


def cheat_ev_usd(gas, gwei, k, margin=MARGIN_USD):
    """Per-attempt EV of submitting a false claim: 2^-K * bounty - gas."""
    f = fee_usd(gas, gwei)
    return 2.0 ** -k * (f + margin) - f


def min_k_economic(gwei, gas_fn, margin=MARGIN_USD, kmax=24):
    """Smallest integer K with cheat EV < 0, where gas itself depends on K.

    Closed form for fixed gas: K* = ceil(log2(1 + margin / fee)); solving it
    against gas(K) directly keeps the K-dependence of the fee honest.
    """
    for k in range(1, kmax + 1):
        if cheat_ev_usd(gas_fn(k), gwei, k, margin) < 0:
            return k
    return kmax


def rejection_paths(sessions):
    """Every measured branch of submitAndVerify at one venue: the honest
    claim (Verified), the lying solver (Rejected — the header leaf's secret
    commitment), and the unknown puzzle (Rejected — the earliest exit). Shows
    the contract's decision tree in gas terms: tampered claims exit before
    the expensive spot-check phase, so rejection costs ~42% less than
    honesty. Only sessions on the current contract (post commitment-fix)
    are pooled."""
    venue = "base-sepolia"
    cutoff = "2026-11-10"          # commitment-fix deployment date
    paths = {"honest claim\n(Verified)": [], "lying solver\n(Rejected)": [],
             "unknown puzzle\n(Rejected)": []}
    for s in sessions:
        if s.get("venue") != venue or s.get("timestamp_utc", "") < cutoff:
            continue
        for r in s["runs"]:
            if r["name"].startswith("verify_honest"):
                paths["honest claim\n(Verified)"].append(r["gas_used"])
            elif r["name"] == "verify_cheat":
                paths["lying solver\n(Rejected)"].append(r["gas_used"])
            elif r["name"] == "verify_unknown_puzzle":
                paths["unknown puzzle\n(Rejected)"].append(r["gas_used"])

    labels = list(paths)
    meds = [float(np.median(paths[k])) for k in labels]
    ns = [len(paths[k]) for k in labels]
    colors = [GAS, CHEAT, FIXED]

    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    bars = ax.bar(labels, meds, color=colors, width=0.55)
    for bar, med, n in zip(bars, meds, ns):
        ax.annotate(f"{med / 1e3:,.0f}k\n(n={n})",
                    (bar.get_x() + bar.get_width() / 2, med),
                    textcoords="offset points", xytext=(0, 4),
                    ha="center", fontsize=8)
    ax.set_ylim(0, max(meds) * 1.18)
    ax.set_ylabel("gas per attempt")
    ax.set_title("Every branch of submitAndVerify (Base Sepolia, K = 8)",
                 fontsize=10)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(FIG / "fig6_rejection_paths.png", dpi=200)
    plt.close(fig)
    print(f"wrote {FIG / 'fig6_rejection_paths.png'}")


def bounty_sensitivity_table(intercept, slope):
    """LaTeX table + PNG: pricing/security outcomes vs the server's margin.

    The margin is the dynamic quantity — the server re-publishes it to the
    FeeQuoteRegistry at will — so this table shows what each quoted value
    does to the client's bounty, the server's profit, and the minimum safe K
    on a cheap (L2) and an expensive (L1 @ 30 gwei) chain, at K = 8.
    """
    margins = [0.10, 0.25, 0.50, 1.00, 2.00]
    g8 = intercept + slope * 8

    def gas_fn(k):
        return intercept + slope * k

    l2_gwei, l1_gwei = 0.05, 30.0
    header = ["margin (USD)", "bounty L2", "server net",
              "forger EV L2", "K* L2", "forger EV L1@30", "K* L1@30"]
    rows = []
    for m in margins:
        bounty_l2 = fee_usd(g8, l2_gwei) + m
        ev_l2 = cheat_ev_usd(g8, l2_gwei, 8, m)
        ev_l1 = cheat_ev_usd(g8, l1_gwei, 8, m)
        rows.append([
            f"{m:.2f}",
            f"{bounty_l2:.3f}",
            f"\\approx {m:.2f}",          # tex; the PNG render swaps in unicode
            f"{ev_l2:+.4f}",
            str(min_k_economic(l2_gwei, gas_fn, m)),
            f"{ev_l1:+.2f}",
            str(min_k_economic(l1_gwei, gas_fn, m)),
        ])

    tex_path = FIG / "bounty_sensitivity.tex"
    lines = [
        "% Bounty sensitivity: outcomes vs the server's quoted margin.",
        "% Generated by plot_paper.py; gas model fitted from bench/evm_results.json.",
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{Bounty pricing outcomes vs the server's quoted margin "
        "(K = 8, gas model fitted from measured runs; L2 at 0.05 gwei, "
        "L1 at 30 gwei). Server net $\\approx$ margin: the gas leg is "
        "reimbursed at cost.}",
        "\\label{tab:bounty_sensitivity}",
        "\\begin{tabular}{|c|c|c|c|c|c|c|}",
        "\\hline",
        " & ".join(f"\\textbf{{{h}}}" for h in header) + " \\\\",
        "\\hline",
    ]
    lines += [" & ".join(r) + " \\\\" for r in rows]
    lines += ["\\hline", "\\end{tabular}", "\\end{table}"]
    tex_path.write_text("\n".join(lines) + "\n")

    # PNG render of the same table (unicode approx; USD units are in the title)
    fig, ax = plt.subplots(figsize=(9.8, 2.6))
    ax.axis("off")
    png_rows = [[c.replace("\\approx ", "≈ ") for c in r] for r in rows]
    tbl = ax.table(cellText=png_rows, colLabels=header, loc="center",
                   cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.5)
    for (r, c), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#e8e8e8")
            cell.set_text_props(weight="bold")
    ax.set_title("Bounty pricing outcomes vs the server's quoted margin (K = 8; "
                 "bounty/EV in USD)", fontsize=11)
    fig.tight_layout()
    png_path = FIG / "bounty_sensitivity.png"
    fig.savefig(png_path, dpi=200)
    plt.close(fig)
    print(f"wrote {tex_path} and {png_path}")


# ---------------------------------------------------------------------------

def main() -> None:
    sessions = json.loads((EVM_ROOT / "bench" / "evm_results.json").read_text())
    by_k = honest_rows(sessions, "K", fixed={"T": 1})
    by_t = honest_rows(sessions, "T", fixed={"K": 8})
    lat_t = latency_stats(sessions, "T", fixed={"K": 8})

    ks = sorted(k for k in by_k if k in (1, 2, 4, 8, 16))
    ts = sorted(t for t in by_t if t in (1, 10, 25, 50, 100))
    sizes = claim_sizes(ts)

    gas_k = np.array([by_k[k]["gas"] for k in ks])
    slope, intercept = np.polyfit(ks, gas_k, 1)          # gas per spot check
    gas_t = np.array([by_t[t]["gas"] for t in ts])
    kk = np.array(sorted(by_k))
    gk = np.array([by_k[k]["gas"] for k in kk])
    g8 = gk[ks.index(8)]
    base = intercept + slope * 8                        # K=8, T-independent logic

    # figures carry data only: axis labels, tick labels and legends. All
    # interpretation lives in docs/FIGURES.md.
    def twin_storey(ax, loc="upper center", ncol=2, y=-0.17):
        ax.legend(fontsize=7.5, loc=loc, bbox_to_anchor=(0.5, y), ncol=ncol,
                  frameon=False)

    # --- fig 1 (a): fig1a_gas_vs_T ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))

    ax.bar(ts, [intercept] * len(ts), width=8, color=FIXED,
           label=f"fixed, {intercept:,.0f}")
    ax.bar(ts, [slope * 8] * len(ts), bottom=[intercept] * len(ts), width=8,
           color=GAS, label=f"8 spot checks, {slope * 8:,.0f}")
    ax.set_xlim(-9, max(ts) * 1.09)
    ax.set_xticks(ts)
    ax.set_ylim(0, max(gas_t) * 1.18)
    ax.set_xlabel("$T$ (sequential steps)")
    ax.set_ylabel("gas per verification")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v / 1e3:,.0f}k"))
    ax.set_title("Gas composition vs $T$", fontsize=10)
    twin_storey(ax, ncol=2)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig1a_gas_vs_T.png", dpi=200)
    plt.close(fig)

    # --- fig 1 (b): fig1b_claim_bytes_vs_T ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))

    cm = [sizes[t]["claim"] for t in ts]
    ax.bar(ts, cm, width=8, color=FIXED, label="claim bytes")
    ax.axhline(32, color=CHEAT, lw=1.2, ls=":", label="root, 32 B")
    ax.set_yscale("log")
    ax.set_ylim(20, 20_000)
    ax.set_xlim(-9, max(ts) * 1.09)
    ax.set_xticks(ts)
    ax.set_xlabel("$T$ (sequential steps)")
    ax.set_ylabel("bytes (log)")
    ax.set_title("On-chain bytes per claim vs $T$", fontsize=10)
    twin_storey(ax, ncol=3)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig1b_claim_bytes_vs_T.png", dpi=200)
    plt.close(fig)


    # --- fig 2 (a): fig2a_gas_vs_K ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))

    gas_line, = ax.plot(ks, gas_k / 1e3, "o-", color=GAS)
    ax.set_xticks(ks)
    ax2 = ax.twinx()
    p_line, = ax2.plot(ks, [2.0 ** -k for k in ks], "x--", color=CHEAT, alpha=0.8)
    ax2.set_yscale("log")
    ax.set_xlabel("spot checks $K$")
    ax.set_ylabel("gas per verification (\u00d710\u00b3)", color=GAS)
    ax2.set_ylabel("false-claim probability $2^{-K}$", color=CHEAT)
    ax2.spines[["top"]].set_visible(False)
    ax2.tick_params(axis="y", colors=CHEAT)
    ax.tick_params(axis="y", colors=GAS)
    ax.set_title("Gas and false-claim probability vs $K$", fontsize=10)
    ax.legend([gas_line, p_line],
              [f"gas = {intercept:,.0f} + {slope:,.0f}\u00b7K",
               r"false-claim probability"],
              loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2,
              frameon=False, fontsize=7.5)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig2a_gas_vs_K.png", dpi=200)
    plt.close(fig)

    # --- fig 2 (b): fig2b_fee_vs_K ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))

    for gwei, label, color in VENUES:
        ax.plot(kk, [fee_usd(g, gwei) for g in gk], "o-", color=color, ms=3.5,
                lw=1.5, label=f"{label}")
    ax.plot(kk, [by_k[k]["fee_eth"] * ETH_USD for k in ks], "X", color="#1a1a1a",
            ms=6.5, zorder=5, label="measured")
    ax.axhline(MARGIN_USD, color=FIXED, ls="--", lw=1, label="server margin")
    ax.set_yscale("log")
    ax.set_xticks(ks)
    ax.set_xlabel("spot checks $K$")
    ax.set_ylabel("fee per verification (USD, log)")
    ax.set_title("Fee per verification vs $K$ — server margin assumed USD 0.50", fontsize=10)
    ax.legend(fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3,
              frameon=False)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig2b_fee_vs_K.png", dpi=200)
    plt.close(fig)


    # --- fig 3 (a): fig3a_ev_vs_K ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    y = np.arange(len(VENUES))
    labels = [v[1] for v in VENUES]

    ax.axhline(0, color="#333333", lw=0.9)
    ax.plot(kk, [MARGIN_USD] * len(kk), "-", color=FEE, lw=2.2, label="honest server")
    for gwei, _label, color in VENUES:
        ax.plot(kk, [cheat_ev_usd(g, gwei, k) for k, g in zip(kk, gk)],
                "o--", color=color, ms=4, lw=1.5, label=f"forger, {gwei:g} gwei")
    ax.set_yscale("symlog", linthresh=0.02)
    ax.set_ylim(-60, 1.2)
    ax.set_yticks([-50, -10, -1, -0.1, -0.02, 0, 0.02, 0.1, 0.5])
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:g}"))
    ax.set_xticks(ks)
    ax.set_xlabel("spot checks $K$")
    ax.set_ylabel("expected value per attempt (USD)")
    ax.set_title("Expected value per claim vs $K$ — server margin assumed USD 0.50", fontsize=10)
    twin_storey(ax, ncol=3)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig3a_ev_vs_K.png", dpi=200)
    plt.close(fig)

    # --- fig 3 (b): fig3b_payment_split ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    y = np.arange(len(VENUES))
    labels = [v[1] for v in VENUES]

    chain_share = [fee_usd(g8, gw) for gw, _l, _c in VENUES]
    margin_pct = [MARGIN_USD / (MARGIN_USD + c) * 100 for c in chain_share]
    chain_pct = [100 - m for m in margin_pct]
    ax.barh(y, margin_pct, color=FEE, height=0.55, label="server margin")
    ax.barh(y, chain_pct, left=margin_pct, color=GAS, height=0.55, label="chain fee")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of client payment (%), K=8")
    ax.set_title("Split of the client's payment — server margin assumed USD 0.50", fontsize=10)
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2,
              frameon=False)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig3b_payment_split.png", dpi=200)
    plt.close(fig)


    # --- fig 4 (a): fig4a_verdict_time_vs_T ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))

    sol_t = np.array([by_t[t]["psolve_ms"] for t in ts])
    s_slope, s_int = np.polyfit(ts, sol_t, 1)          # ms of sequential solve per step
    t_meas = np.array(ts, dtype=float)
    t_proj = np.logspace(0, 9.5, 240)
    y_line = (s_int + s_slope * t_proj) / 1000.0
    lat = statistics.median([lat_t[t]["med"] for t in ts])
    meas_max = float(max(ts))

    h_meas, = ax.plot(t_meas, (s_int + s_slope * t_meas) / 1000.0, "o-", color=SOLVE,
                      ms=5, lw=1.2, zorder=5, label="recompute locally, measured")
    h_ext, = ax.plot(t_proj[t_proj >= meas_max], y_line[t_proj >= meas_max], "--",
                     color=SOLVE, lw=1.6, label="recompute locally, extrapolated")
    h_chain, = ax.plot([1, 1e9], [lat, lat], "--", color=LAT, lw=1.8,
                       label="on-chain verdict, one block")
    cross = (lat - s_int / 1000.0) / (s_slope / 1000.0)
    ax.plot([cross], [lat], "o", mfc="white", mec=LAT, ms=8, zorder=6)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(1, 1e9)
    ax.set_ylim(1e-3, 2e5)
    ax.set_xlabel("$T$ (sequential steps, log)")
    ax.set_ylabel("wall-clock to a verdict (s, log)")
    ax.set_title("Time to a trusted verdict vs $T$", fontsize=10)
    ax.legend([h_meas, h_ext, h_chain],
              ["recompute locally, measured", "recompute locally, extrapolated",
               "on-chain verdict, one block"],
              fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=2,
              frameon=False)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig4a_verdict_time_vs_T.png", dpi=200)
    plt.close(fig)

    # --- fig 4 (b): fig4b_offchain_phases_vs_T ---
    fig, ax = plt.subplots(figsize=(6.4, 4.2))

    ax.plot(ts, [by_t[t]["psetup_ms"] for t in ts], "o-", color=GAS, label="PSetup")
    ax.plot(ts, [by_t[t]["pgen_ms"] for t in ts], "s--", color=FEE, label="PGen")
    ax.plot(ts, [by_t[t]["psolve_ms"] for t in ts], "^--", color=SOLVE, label="PSolve")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(1.2, 400)
    ax.set_xlabel("$T$ (log)")
    ax.set_ylabel("off-chain time (ms, log)")
    ax.set_title("Off-chain phases vs $T$", fontsize=10)
    ax.legend(fontsize=7.5, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3,
              frameon=False)
    style(ax)

    fig.tight_layout(rect=(0, 0.02, 1, 1))
    fig.savefig(FIG / "fig4b_offchain_phases_vs_T.png", dpi=200)
    plt.close(fig)


    # --- fig 5 -------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    gwei_grid = np.logspace(-3, 2, 240)

    def gas_fn(k):
        return intercept + slope * k

    k_curve = [min_k_economic(g, gas_fn) for g in gwei_grid]
    ax.step(gwei_grid, k_curve, where="post", color=GAS, lw=2.2)
    ax.fill_between(gwei_grid, 0, k_curve, step="post", color=CHEAT, alpha=0.08)
    handles = []
    for gwei, label, color in VENUES:
        k_needed = min_k_economic(gwei, gas_fn)
        h, = ax.plot([gwei], [k_needed], "D", color=color, ms=9, zorder=5,
                     label=f"{label}: K={k_needed}")
        handles.append(h)
    ax.set_xscale("log")
    ax.set_xlabel("base fee at verification (gwei, log)")
    ax.set_ylabel("spot checks $K$")
    ax.set_title("Minimum $K$ for a non-positive forger EV — server margin assumed USD 0.50", fontsize=10)
    ax.set_ylim(-0.6, 14)
    ax.set_xlim(1e-3, 1e2)
    ax.legend(fontsize=7.5, loc="upper right", frameon=False)
    style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "fig5_security_map.png", dpi=200)
    plt.close(fig)

    # ------------------------------------------------------------ printout
    print("wrote fig1a..fig5 to bench/figures/\n")
    rejection_paths(sessions)
    bounty_sensitivity_table(intercept, slope)
    print(f"K-fit: gas(K) = {intercept:,.0f} + {slope:,.0f}*K   (K=8 -> {base:,.0f} at T=1)\n")
    print(f"{'T':>4} {'gas':>8} {'logic':>8} {'resid':>8} {'res%':>6} "
          f"{'claim B':>8} {'max gate':>9} {'PSolve ms':>10} {'lat s':>7} {'n':>3}")
    for t, g in zip(ts, gas_t):
        s = sizes[t]
        lt = lat_t.get(t, {"med": float("nan"), "n": 0})
        print(f"{t:>4} {g:>8,.0f} {base:>8,.0f} {g - base:>8,.0f} "
              f"{(g - base) / g * 100:>5.1f}% {s['claim']:>8,} "
              f"{s['max_gate']:>9,} {by_t[t]['psolve_ms']:>10.2f} {lt['med']:>7.1f} {lt['n']:>3}")
    print(f"\nsequential solve: {s_int:.3f} ms + {s_slope:.6f} ms/step "
          f"({s_slope * 1000:.1f} us/step) -> crossover at T = {cross:,.0f}\n")
    print(f"{'K':>3} {'gas':>9} " + " ".join(f"{v[0]:>9}gwei" for v in VENUES)
          + f" {'EV L2':>9} {'EV L1-5':>9}")
    for k, g in zip(ks, gk):
        print(f"{k:>3} {g:>9,.0f} " + " ".join(f"${fee_usd(g, v[0]):>10.4f}" for v in VENUES)
              + f" {cheat_ev_usd(g, 0.05, k):>9.4f} {cheat_ev_usd(g, 5.0, k):>9.4f}")
    print("\nmin K for cheat EV < 0:  "
          + "   ".join(f"{lbl} -> K={min_k_economic(gw, gas_fn)}"
                      for gw, lbl, _c in VENUES))


if __name__ == "__main__":
    main()
