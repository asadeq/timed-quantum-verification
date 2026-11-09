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

    # de-dupe (venue, T, K): last cycle wins
    by_vtk: dict[tuple[str, int, int], dict] = {}
    for c in cycles:
        by_vtk[(c["venue"], c.get("T", 1), c.get("K", 8))] = c

    # Primary series = the latest live-chain venue (Base Sepolia today); anvil
    # remains the fallback when no live sweep has been recorded yet.
    live_venues = [c["venue"] for c in cycles if c["venue"].startswith("sepolia")]
    primary_venue = live_venues[-1] if live_venues else "anvil"

    # ---- series ------------------------------------------------------------
    # Panel A: only the T-sweep session. Mixing in the (T=1, K=8) cycle from
    # the K-sweep session re-introduces cross-session anvil gas-price drift
    # (~0.3%), which is larger than the true T-effect and reads as a spike.
    t_sessions: dict[tuple, set] = defaultdict(set)
    for c in cycles:
        if c.get("K", 8) == 8:
            t_sessions[(c["venue"], c["s_idx"])].add(c.get("T", 1))
    best = max(t_sessions, key=lambda kk: (len(t_sessions[kk]), kk[1])) \
        if t_sessions else None
    tk8 = sorted((c["T"], c) for c in cycles
                 if best and (c["venue"], c["s_idx"]) == best and c.get("K", 8) == 8)
    t1k = sorted((k, c) for (_, t, k), c in by_vtk.items()
                 if t == 1 and c["venue"] == primary_venue)

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4))

    # A. profit vs T at K=8 (single-session; baseline-anchored so flatness reads)
    ax = axes[0]
    if tk8:
        ts = [t for t, _ in tk8]
        pf = [c["server_profit_wei"] / 1e12 for _, c in tk8]   # wei -> µETH
        drift = (pf[-1] - pf[0]) / pf[0] * 100 if len(pf) > 1 else 0.0
        ax.plot(ts, pf, "o-", color=ACCENT)
        ax.set_ylim(0, max(pf) * 1.25)
        ax.set_xlabel("Time-lock length T (sequential steps)")
        ax.set_ylabel("Server net profit (µETH)")
        ax.set_title(f"(a) Net server profit vs T, K=8", fontsize=10)

    # B. honest vs cheat EV, linear USD — the comparison IS the message
    ax = axes[1]
    if t1k:
        ks = [k for k, _ in t1k]
        pf = [c["server_profit_wei"] / 1e18 * eth_usd for _, c in t1k]
        ev = [((2.0 ** -k) * c["bounty_wei"] - c["gas_cost_wei"]) / 1e18 * eth_usd
              for k, c in t1k]
        ax.plot(ks, pf, "o-", color=ACCENT, label="honest: keep the bounty")
        ax.plot(ks, ev, "x--", color=WARN, label="forger, 2^-K·bounty − gas")
        ax.axhline(0, color=FLAT, lw=0.8)
        ax.set_xlim(min(ks) - 0.6, max(ks) + 0.8)
        ax.set_xlabel("Spot checks K")
        ax.set_ylabel("Expected value per attempt (USD)")
        ax.set_title("(b) Expected value per claim vs K", fontsize=10)
        ax.set_ylim(-0.12, max(pf) * 1.25)
        ax.legend(loc="upper left", fontsize=6.6)

    # C. client cost vs K
    ax = axes[2]
    if t1k:
        ks = [k for k, _ in t1k]
        usd = [c["bounty_wei"] / 1e18 * eth_usd for _, c in t1k]
        ax.plot(ks, usd, "s-", color=ACCENT, label="escrowed bounty")
        ax.set_xlim(min(ks) - 1.2, max(ks) + 1.2)
        ax.set_ylim(0, max(usd) * 1.22)
        ax.set_xlabel("Spot checks K")
        ax.set_ylabel("Escrowed bounty (USD)")
        ax.set_title("(c) Client cost vs K", fontsize=10)
        ax.legend(fontsize=8)

    fig.suptitle(f"Commerce experiment (ETH = ${eth_usd:,.0f})", fontsize=12)
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
