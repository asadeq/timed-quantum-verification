#!/usr/bin/env python3
"""
Paper figures — three 2-panel figures, Sepolia only, new (escrow) contract.

  fig1_flat_in_T.png   (a) on-chain gas vs T + off-chain solve time (twin axis)
                       (b) time-to-receipt latency vs T
  fig2_linear_in_K.png (a) gas vs K with cheat probability 2^-K (twin axis)
                       (b) fee in USD vs K
  fig3_payoff.png      (a) server profit vs K with cheating expected value
                       (b) client bounty decomposition: gas + margin per K

Deliberately caption-free: axis labels and legends only. All data from live
Sepolia runs against the escrow contract (evm_results.json sweeps +
commerce_ledger.json cycles); latest session wins per parameter value.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent
FIG = EVM_ROOT / "bench" / "figures"

REF_GWEI = 1.0  # reference gas price for normalized fee reporting

GAS = "#0f62fe"      # on-chain gas
FEE = "#198038"      # money
SOLVE = "#e8a33d"    # off-chain work
LAT = "#6929c4"      # latency
CHEAT = "#da1e28"


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(True, alpha=0.25, lw=0.5)


def honest_rows(sessions, key, fixed):
    """Latest sepolia session per `key` value (with `fixed` params matched)
    -> mean honest-run stats."""
    latest = {}
    for s in sessions:
        if not s.get("venue", "").startswith("sepolia"):
            continue
        p = s.get("params", {})
        if key not in p or any(p.get(k) != v for k, v in fixed.items()):
            continue
        latest[p[key]] = s
    out = {}
    for v, s in latest.items():
        runs = [r for r in s["runs"] if r["name"].startswith("verify_honest")]
        n = len(runs)
        o = s.get("offchain_ms", {})
        out[v] = {
            "gas": sum(r["gas_used"] for r in runs) / n,
            "fee_eth": sum(r["gas_used"] * r["effective_gas_price_wei"] for r in runs)
            / n / 1e18,
            "price_gwei": sum(r["effective_gas_price_wei"] for r in runs) / n / 1e9,
            "latency_s": sum(r["latency_ms"] for r in runs) / n / 1000.0,
            "solve_ms": o.get("psolve_ms", float("nan")),
            "solve_err": (
                o.get("psolve_ms", float("nan")) - o.get("psolve_ms_min", float("nan")),
                o.get("psolve_ms_max", float("nan")) - o.get("psolve_ms", float("nan")),
            ),
            "solve_n": o.get("psolve_ms_n", 1),
        }
    return out


def commerce_cycles(key):
    """Latest sepolia sweep session per `key` value -> commerce cycle stats."""
    sessions = json.loads((EVM_ROOT / "bench" / "commerce_ledger.json").read_text())
    latest = {}
    for s in sessions:
        if not s.get("venue", "").startswith("sepolia"):
            continue
        for c in s.get("cycles", []):
            latest[c[key]] = c
    return latest


def main() -> None:
    sessions = json.loads((EVM_ROOT / "bench" / "evm_results.json").read_text())
    by_k = honest_rows(sessions, "K", fixed={"T": 1})
    by_t = honest_rows(sessions, "T", fixed={"K": 8})
    cyc_k = commerce_cycles("K")
    cyc_t = commerce_cycles("T")

    ks = sorted(k for k in by_k if k in (1, 2, 4, 8, 16))
    ts = sorted(t for t in by_t if by_t[t].get("solve_ms") == by_t[t].get("solve_ms")
                and t in (1, 10, 25, 50, 100))

    # ---------------------------------------------------------------- fig 1
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    ax = axes[0]
    gas_line, = ax.plot(ts, [by_t[t]["gas"] / 1e3 for t in ts], "o-", color=GAS,
                        label="on-chain verification gas")
    ax2 = ax.twinx()
    errs = [by_t[t]["solve_err"] for t in ts]
    sol_line, _, _ = ax2.errorbar(ts, [by_t[t]["solve_ms"] for t in ts],
                                  yerr=[[e[0] for e in errs], [e[1] for e in errs]],
                                  fmt="s--", color=SOLVE, capsize=3)
    ax.set_xlabel("Time-lock length $T$ (sequential steps)")
    ax.set_ylabel("on-chain gas (×10³)", color=GAS)
    ax2.set_ylabel("off-chain solve time (ms)", color=SOLVE)
    ax2.spines[["top"]].set_visible(False)
    ax2.tick_params(axis="y", colors=SOLVE)
    ax.tick_params(axis="y", colors=GAS)
    ax.legend([gas_line, sol_line],
              ["on-chain verification gas",
               f"off-chain solve time (median, n={by_t[ts[0]]['solve_n']})"],
              loc="upper left", fontsize=8)
    style(ax)

    ax = axes[1]
    ax.plot(ts, [by_t[t]["latency_s"] for t in ts], "o-", color=LAT)
    med = sorted(by_t[t]["latency_s"] for t in ts)[len(ts) // 2]
    ax.axhline(med, color="#8d8d8d", lw=0.8, ls="--")
    ax.set_xlabel("Time-lock length $T$ (sequential steps)")
    ax.set_ylabel("time to receipt (s)")
    style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "fig1_flat_in_T.png", dpi=200)
    plt.close(fig)

    # ---------------------------------------------------------------- fig 2
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    ax = axes[0]
    gas_line, = ax.plot(ks, [by_k[k]["gas"] / 1e3 for k in ks], "o-", color=GAS)
    ax2 = ax.twinx()
    p_line, = ax2.plot(ks, [2.0 ** -k for k in ks], "x--", color=CHEAT, alpha=0.7)
    ax2.set_yscale("log")
    ax.set_xlabel("Spot checks $K$")
    ax.set_ylabel("on-chain gas (×10³)", color=GAS)
    ax2.set_ylabel(r"cheat probability $2^{-K}$", color=CHEAT)
    ax2.spines[["top"]].set_visible(False)
    ax2.tick_params(axis="y", colors=CHEAT)
    ax.tick_params(axis="y", colors=GAS)
    ax.legend([gas_line, p_line],
              ["verification gas (linear)", r"cheat probability $2^{-K}$"],
              loc="center left", fontsize=8)
    style(ax)

    ax = axes[1]
    ref = [by_k[k]["gas"] * REF_GWEI * 1e9 / 1e18 for k in ks]
    ax.plot(ks, ref, "--", color=FEE, label=f"at {REF_GWEI:g} gwei reference")
    ax.plot(ks, [by_k[k]["fee_eth"] for k in ks], "o", color=GAS, alpha=0.65,
            label="measured (live Sepolia prices)")
    ax.set_yscale("log")
    ax.set_xlabel("Spot checks $K$")
    ax.set_ylabel("fee per verification (ETH)")
    ax.legend(fontsize=8)
    style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "fig2_linear_in_K.png", dpi=200)
    plt.close(fig)

    # ---------------------------------------------------------------- fig 3
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    ax = axes[0]
    pks = sorted(cyc_k)
    profit = [cyc_k[k]["server_profit_wei"] / 1e18 for k in pks]
    ev = [((2.0 ** -k) * cyc_k[k]["bounty_wei"] - cyc_k[k]["gas_cost_wei"])
          / 1e18 for k in pks]
    ax.plot(pks, profit, "o-", color=FEE, label="honest server profit")
    ax.plot(pks, ev, "x--", color=CHEAT, label="cheating EV $2^{-K}B-gas$")
    ax.axhline(0, color="#8d8d8d", lw=0.8)
    ax.set_xlabel("Spot checks $K$")
    ax.set_ylabel("expected value per claim (ETH)")
    ax.legend(fontsize=8)
    style(ax)

    ax = axes[1]
    gas_share = [cyc_k[k]["gas_cost_wei"] / 1e18 for k in pks]
    margin = [cyc_k[k]["server_profit_wei"] / 1e18 for k in pks]
    ax.bar(pks, margin, color=FEE, label="server margin")
    ax.bar(pks, gas_share, bottom=margin, color=GAS, label="server gas")
    ax.set_xlabel("Spot checks $K$")
    ax.set_ylabel("client bounty (ETH)")
    ax.legend(fontsize=8)
    style(ax)
    fig.tight_layout()
    fig.savefig(FIG / "fig3_payoff.png", dpi=200)
    plt.close(fig)

    print("wrote fig1_flat_in_T.png, fig2_linear_in_K.png, fig3_payoff.png")
    print(f"\nSepolia data (all values ETH):")
    print(f"{'K':>3} {'gas':>10} {'price gwei':>11} {'fee@ref':>12} {'fee live':>12} "
          f"{'latency s':>10} {'profit':>12}")
    for k in ks:
        c = cyc_k.get(k)
        ref_fee = by_k[k]["gas"] * REF_GWEI * 1e9 / 1e18
        print(f"{k:>3} {by_k[k]['gas']:>10,.0f} {by_k[k]['price_gwei']:>11.4f} "
              f"{ref_fee:>12.7f} {by_k[k]['fee_eth']:>12.9f} "
              f"{by_k[k]['latency_s']:>10.1f} "
              f"{(c['server_profit_wei'] / 1e18) if c else float('nan'):>12.9f}")
    print(f"{'T':>3} {'gas':>10} {'price gwei':>11} {'fee live':>12} {'latency s':>10} {'solve ms':>9}")
    for t in ts:
        print(f"{t:>3} {by_t[t]['gas']:>10,.0f} {by_t[t]['price_gwei']:>11.4f} "
              f"{by_t[t]['fee_eth']:>12.9f} "
              f"{by_t[t]['latency_s']:>10.1f} {by_t[t]['solve_ms']:>9.2f}")


if __name__ == "__main__":
    main()
