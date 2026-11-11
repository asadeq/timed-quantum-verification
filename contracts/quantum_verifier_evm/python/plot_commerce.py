#!/usr/bin/env python3
"""
Render the commerce experiment ledger into bench/figures/commerce_profit.png
and bench/figures/pricing_window.png.

Reads bench/commerce_ledger.json (appended by experiment_commerce.py and
experiment_pricing.py) and plots:

  A. server profit vs T (at K=8)      — profitability is flat in the time-lock
  B. server profit vs K (at T=1), with the cheating expected value 2^-K*bounty-gas
  C. client cost vs K                 — the linear cost of confidence

pricing_window.png (from the `experiment: "pricing"` session) shows the effect
of the bounty level itself: the measured server-net step at the reservation
price (lambda = 1) against the forger's expected value, which grows with the
bounty — the operating window [1, lambda*] where service is available AND the
bounty is not worth attacking at the chosen K.
"""

from __future__ import annotations

import json
import math
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


def render_pricing_window(session: dict, eth_usd: float) -> None:
    """The bounty-level experiment, as two single-message figures:

    pricing_service_vs_lambda.png — the measured server-net step at the
        reservation price: below lambda = 1 the market does not clear
        (refusal + reclaim);
    pricing_security_vs_lambda.png — the minimum safe K the bounty demands,
        K_req = log2(lambda*B/gas), crossing the client's chosen K at
        lambda* = 2^K*gas/B: overpaying raises the security you need.
    """
    p = session["params"]
    k = p["K"]
    fair = p["fair_wei"]                      # lambda=1 bounty (gasLeg + quote)
    cycles = session["cycles"]

    accepted = [c for c in cycles if c["decision"] == "accepted"]
    refused = [c for c in cycles if c["decision"] == "refused"]
    if not accepted:
        print("pricing_window: no accepted cycles — nothing to plot")
        return
    gas_forge = sorted(c["gas_cost_wei"] for c in accepted)[len(accepted) // 2]
    lam_star = (2.0 ** k) * gas_forge / fair

    # ---- service: does the market clear? --------------------------------
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    ax.plot([c["lambda"] for c in accepted],
            [c["server_net_wei"] / 1e18 * eth_usd for c in accepted],
            "o-", color=ACCENT, label="accepted — server net (measured)")
    if refused:
        ax.plot([c["lambda"] for c in refused],
                [0] * len(refused), "x", color=WARN, markersize=10,
                label="refused — no service (measured)")
    ax.axvline(1.0, color="#8d8d8d", lw=1.0, ls=":",
               label="server reservation price ($\\lambda$ = 1)")
    ax.axhline(0, color="#8d8d8d", lw=0.8)
    ax.set_xlim(0.45, 2.2)
    net_max = max(c["server_net_wei"] for c in accepted) / 1e18 * eth_usd
    ax.set_ylim(-0.06, net_max * 1.25)
    ax.set_xlabel("bounty multiplier $\\lambda$ over the fair price")
    ax.set_ylabel("server net per claim (USD)")
    ax.set_title("Below the reservation price, no one serves you", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(OUT.parent / "pricing_service_vs_lambda.png", dpi=150)
    plt.close(fig)

    # ---- security: is the bounty worth attacking? ------------------------
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    xs = [0.5, lam_star * 1.12]
    k_req = [math.log2(lam * fair / gas_forge) for lam in xs]
    ax.plot(xs, k_req, "-", color=WARN,
            label="minimum safe K: $\\log_2(\\lambda B / gas)$")
    ax.axhline(k, color="#555", lw=1.0, ls="--",
               label=f"client's chosen K = {k}")
    ax.plot([lam_star], [k], "o", color=WARN, markersize=7)
    ax.annotate(f"$\\lambda^* = 2^K \\cdot gas / B$ = {lam_star:.2f}",
                (lam_star, k), xytext=(-8, -16), textcoords="offset points",
                fontsize=9, color=WARN, ha="right")
    ax.axvspan(1.0, lam_star, color=ACCENT, alpha=0.08,
               label=f"operating window [1, {lam_star:.2f}]")
    ax.axvline(1.0, color="#8d8d8d", lw=1.0, ls=":")
    ax.set_xlim(0.5, lam_star * 1.12)
    ax.set_ylim(k - 2.2, k + 1.2)
    ax.set_xlabel("bounty multiplier $\\lambda$ over the fair price")
    ax.set_ylabel("minimum safe K for this bounty")
    ax.set_title("Overpaying raises the security you need", fontsize=10)
    ax.grid(alpha=0.3)
    ax.legend(fontsize=7.5, loc="upper left", frameon=False)
    fig.tight_layout()
    fig.savefig(OUT.parent / "pricing_security_vs_lambda.png", dpi=150)
    plt.close(fig)

    print("wrote pricing_service_vs_lambda.png, pricing_security_vs_lambda.png")
    print(f"   lambda* (K={k}, measured gas) = {lam_star:.2f}")


def main() -> None:
    all_sessions = json.loads(LEDGER.read_text())
    # the pricing experiment has a different cycle schema — it feeds
    # render_pricing_window, not the commerce panels
    sessions = [s for s in all_sessions if s.get("experiment") != "pricing"]
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

    # ---- commerce panel: commerce_profit_vs_T ----
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
    if tk8:
        ts = [t for t, _ in tk8]
        pf = [c["server_profit_wei"] / 1e12 for _, c in tk8]   # wei -> µETH
        drift = (pf[-1] - pf[0]) / pf[0] * 100 if len(pf) > 1 else 0.0
        ax.plot(ts, pf, "o-", color=ACCENT)
        ax.set_ylim(0, max(pf) * 1.25)
        ax.set_xlabel("Time-lock length T (sequential steps)")
        ax.set_ylabel("Server net profit (µETH)")
        ax.set_title(f"Net server profit vs T, K=8", fontsize=10)

    # B. honest vs cheat EV, linear USD — the comparison IS the message
    fig.tight_layout()
    fig.savefig(OUT.parent / "commerce_profit_vs_T.png", dpi=150)
    plt.close(fig)

    # ---- commerce panel: commerce_ev_vs_K ----
    fig, ax = plt.subplots(figsize=(6.4, 4.4))
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
        ax.set_title("Expected value per claim vs K", fontsize=10)
        ax.set_ylim(-0.12, max(pf) * 1.25)
        ax.legend(loc="upper left", fontsize=6.6)

    # C. client cost vs K
    fig.tight_layout()
    fig.savefig(OUT.parent / "commerce_ev_vs_K.png", dpi=150)
    plt.close(fig)


    print("wrote commerce_profit_vs_T.png, commerce_ev_vs_K.png")

    pricing_sessions = [s for s in all_sessions if s.get("experiment") == "pricing"]
    if pricing_sessions:
        render_pricing_window(pricing_sessions[-1], eth_usd)

    print(f"\n{'venue':>16} {'T':>4} {'K':>3} {'bounty ETH':>12} {'server net ETH':>16} "
          f"{'~USD':>8} {'solve ms':>9}")
    for (v, t, k), c in sorted(by_vtk.items()):
        print(f"{v[:16]:>16} {t:>4} {k:>3} {c['bounty_wei'] / 1e18:>12.6f} "
              f"{c['server_profit_wei'] / 1e18:>16.8f} "
              f"{c['server_profit_wei'] / 1e18 * eth_usd:>8.3f} {c['solve_ms']:>9.0f}")


if __name__ == "__main__":
    main()
