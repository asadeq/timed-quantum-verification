#!/usr/bin/env python3
"""
Render the commerce experiment ledger into bench/figures/commerce_profit.png.

Reads bench/commerce_ledger.json (appended by experiment_commerce.py) and plots:

  A. server profit vs T (at K=8)      — profitability is flat in the time-lock
  B. server profit vs K (at T=1), with the cheating expected value 2^-K*bounty-gas
  C. client cost vs K                 — the linear cost of confidence
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
LEDGER = EVM_ROOT / "bench" / "commerce_ledger.json"
OUT = EVM_ROOT / "bench" / "figures" / "commerce_profit.png"

ACCENT = "#0f62fe"
WARN = "#da1e28"
FLAT = "#8d8d8d"


def main() -> None:
    sessions = json.loads(LEDGER.read_text())
    cycles = [c | {"venue": s.get("venue", "?"), "eth_usd": s.get("eth_usd", 3000.0),
                   "s_idx": i}
              for i, s in enumerate(sessions) for c in s.get("cycles", [])]
    if len(cycles) < 2:
        raise SystemExit("need >=2 cycles in the ledger (run experiment_commerce.py --sweep-t / --sweep-k)")

    eth_usd = cycles[-1]["eth_usd"]

    # de-dupe (venue, T, K): last cycle wins; sweeps are per-venue so the
    # live Sepolia cycles never silently replace the systematic anvil ones
    by_vtk: dict[tuple[str, int, int], dict] = {}
    for c in cycles:
        by_vtk[(c["venue"], c.get("T", 1), c.get("K", 8))] = c
    by_tk = {("anvil", t, k): c for (_, t, k), c in by_vtk.items() if c["venue"] == "anvil"}
    live = {(v, t, k): c for (v, t, k), c in by_vtk.items() if v.startswith("sepolia")}

    # ---- series ------------------------------------------------------------
    # Panel A: only the T-sweep session. Mixing in the (T=1, K=8) cycle from
    # the K-sweep session re-introduces cross-session anvil gas-price drift
    # (~0.3%), which is larger than the true T-effect and reads as a spike.
    t_sessions: dict[tuple, set] = defaultdict(set)
    for c in cycles:
        if c.get("K", 8) == 8:
            t_sessions[(c["venue"], c["s_idx"])].add(c.get("T", 1))
    best = max(t_sessions, key=lambda kk: len(t_sessions[kk])) if t_sessions else None
    tk8 = sorted((c["T"], c) for c in cycles
                 if best and (c["venue"], c["s_idx"]) == best and c.get("K", 8) == 8)
    t1k = sorted((k, c) for (_, t, k), c in by_tk.items() if t == 1)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))

    # A. profit vs T at K=8 (single-session; baseline-anchored so flatness reads)
    ax = axes[0]
    if tk8:
        ts = [t for t, _ in tk8]
        pf = [c["server_profit_wei"] / 1e18 for _, c in tk8]
        drift = (pf[-1] - pf[0]) / pf[0] * 100 if len(pf) > 1 else 0.0
        ax.plot(ts, pf, "o-", color=ACCENT)
        ax.set_ylim(0, max(pf) * 1.25)
        for t, p in zip(ts, pf):
            ax.annotate(f"{p * 1e6:.1f}", (t, p), textcoords="offset points",
                        xytext=(0, 7), fontsize=8, color=FLAT, ha="center")
        ax.set_xlabel("Time-lock length T (sequential steps)")
        ax.set_ylabel("Server net profit (ETH ×10⁻⁶)")
        ax.set_title(f"A. Profit vs T (K=8) — flat: {drift:+.2f}% over T={ts[0]}→{ts[-1]}")
        ax.text(0.02, 0.04, "labels: profit in µETH; variation is bitmap/tree\n"
                            "growth, not time-lock cost — the chain never re-runs T",
                transform=ax.transAxes, fontsize=7.5, color=FLAT)

    # B. honest vs cheat EV, linear USD — the comparison IS the message
    ax = axes[1]
    if t1k:
        ks = [k for k, _ in t1k]
        pf = [c["server_profit_wei"] / 1e18 * eth_usd for _, c in t1k]
        ev = [((2.0 ** -k) * c["bounty_wei"] - c["gas_cost_wei"]) / 1e18 * eth_usd
              for k, c in t1k]
        ax.plot(ks, pf, "o-", color=ACCENT, label="honest: keep the bounty")
        ax.plot(ks, ev, "x--", color=WARN, label="cheat: 2^-K·bounty − gas")
        for k, e in zip(ks, ev):
            ax.annotate(f"${e:+.3f}", (k, e), textcoords="offset points",
                        xytext=(4, -12), fontsize=8, color=WARN)
        ax.axhline(0, color=FLAT, lw=0.8)
        for (_, _, k), c in sorted(live.items()):
            lp = c["server_profit_wei"] / 1e18 * eth_usd
            ax.plot([k], [lp], "D", color="#198038", markersize=8,
                    label=f"live Sepolia (K={k})")
        ax.set_xlabel("Spot checks K (cheat probability 2^-K)")
        ax.set_ylabel("Expected value per attempt (USD)")
        ax.set_title("B. Honesty strictly dominates at every K")
        ax.legend(loc="center left", fontsize=8)

    # C. client cost vs K
    ax = axes[2]
    if t1k:
        ks = [k for k, _ in t1k]
        bounty = [c["bounty_wei"] / 1e18 for _, c in t1k]
        ax.plot(ks, bounty, "s-", color=ACCENT, label="client cost (escrowed bounty)")
        usd = [b * eth_usd for b in bounty]
        for k, b, u in zip(ks, bounty, usd):
            ax.annotate(f"${u:.2f}", (k, b), textcoords="offset points",
                        xytext=(6, 4), fontsize=8, color=FLAT)
        ax.set_xlabel("Spot checks K")
        ax.set_ylabel("Escrowed bounty (ETH)")
        ax.set_title(f"C. Client cost vs K (@ ${eth_usd:,.0f}/ETH)")
        ax.legend()

    fig.suptitle("PV-CVQC commerce experiment — client escrow, server profit, cheat economics",
                 fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150)
    print(f"wrote {OUT}")

    print(f"\n{'venue':>16} {'T':>4} {'K':>3} {'bounty ETH':>12} {'server net ETH':>16} "
          f"{'~USD':>8} {'solve ms':>9}")
    for (v, t, k), c in sorted(by_vtk.items()):
        print(f"{v[:16]:>16} {t:>4} {k:>3} {c['bounty_wei'] / 1e18:>12.6f} "
              f"{c['server_profit_wei'] / 1e18:>16.8f} "
              f"{c['server_profit_wei'] / 1e18 * eth_usd:>8.3f} {c['solve_ms']:>9.0f}")


if __name__ == "__main__":
    main()
