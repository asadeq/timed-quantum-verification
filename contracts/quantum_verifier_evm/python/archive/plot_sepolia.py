#!/usr/bin/env python3
"""
One-figure Sepolia summary: all three user-facing metrics (gas, ETH fee,
latency) for honest verifications, across K and T.

Layout: rows = metric (gas / fee / latency), columns = sweep axis (K, T).
Fee curves use a fixed 1 gwei reference price so they show protocol cost
rather than Sepolia's fluctuating base fee (see fee_volatility.png in the
parent directory for the market-price story).

Output: bench/figures/sepolia/sepolia_metrics.png
        (only live-Sepolia sessions are used; anvil is excluded by design)

Usage:
    uv run python python/plot_sepolia.py [--eth-usd 3000] [--ref-gwei 1.0]
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import defaultdict
from pathlib import Path

EVM_ROOT = Path(__file__).resolve().parent.parent
BENCH = EVM_ROOT / "bench" / "evm_results.json"

CHAIN_NAMES = {"31337": "anvil", "11155111": "sepolia", "84532": "base-sepolia"}


def short_venue(session: dict) -> str:
    v = session.get("venue", "?")
    if v.startswith("http"):
        cid = str(session.get("chain_id", ""))
        return CHAIN_NAMES.get(cid, f"chain-{cid}")
    return v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eth-usd", type=float, default=3000.0)
    ap.add_argument("--ref-gwei", type=float, default=1.0,
                    help="gas price used to normalize fee curves")
    args = ap.parse_args()

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    sessions = [s for s in json_sessions()
                if short_venue(s) in ("sepolia", "base-sepolia")]
    if not sessions:
        raise SystemExit("no sepolia sessions in bench/evm_results.json")

    # Latest session per (K, T) combination wins: sessions are in file order,
    # and newer ones use the current wire format — older Ethereum-Sepolia
    # sessions predate the non-reusable-list removal and would mix a different
    # gas profile into the fits.
    latest: dict[tuple[int, int], dict] = {}
    for s in sessions:
        p = s.get("params", {})
        latest[(p.get("K", 8), p.get("T", 1))] = s

    # agg[axis][x] = dict of metric lists
    agg = {a: defaultdict(lambda: defaultdict(list)) for a in ("K", "T")}
    for (k, t), s in latest.items():
        for r in s["runs"]:
            if not r["name"].startswith("verify_honest"):
                continue
            gas = r["gas_used"]
            # K curve only from K-sweep sessions (T=1); T curve only from
            # T-sweep sessions (K=8) — otherwise the T=1 point averages
            # across every K value of the K sweep.
            if t == 1:
                m = agg["K"][k]
                m["gas"].append(gas)
                m["fee"].append(gas * args.ref_gwei / 1e9)  # ETH @ ref price
                m["lat"].append(r["latency_ms"] / 1000)
            if k == 8:
                m = agg["T"][t]
                m["gas"].append(gas)
                m["fee"].append(gas * args.ref_gwei / 1e9)  # ETH @ ref price
                m["lat"].append(r["latency_ms"] / 1000)

    # Off-chain solver time (the cost being avoided) per T, for contrast.
    off_t: dict[int, float] = {}
    for s in latest.values():
        t = s.get("params", {}).get("T", 1)
        oc = s.get("offchain_ms", {})
        if oc:
            off_t[t] = oc.get("psolve_ms", 0.0)

    def series(axis: str, metric: str) -> tuple[list, list]:
        d = agg[axis]
        xs = sorted(d)
        return xs, [st.mean(d[x][metric]) for x in xs]

    n_samples = max(len(agg["K"][x]["gas"]) for x in agg["K"])
    kx, kg = series("K", "gas")
    tx, tg = series("T", "gas")
    _, kf = series("K", "fee")
    _, tf = series("T", "fee")
    _, kl = series("K", "lat")
    _, tl = series("T", "lat")

    # Linear fits for the annotation lines.
    def fit(xs, ys):
        n = len(xs)
        sx, sy = sum(xs), sum(ys)
        sxy = sum(x * y for x, y in zip(xs, ys))
        sxx = sum(x * x for x in xs)
        slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
        return slope, (sy - slope * sx) / n

    fig, axes = plt.subplots(3, 2, figsize=(12, 10))

    # --- Row 1: gas ---------------------------------------------------------
    ax = axes[0][0]
    ax.plot(kx, kg, "o-", color="#0f62fe")
    sl, ic = fit(kx, kg)
    ax.plot(kx, [sl * x + ic for x in kx], "--", color="#999",
            label=f"fit: {sl:,.0f} gas/check")
    for x, y in zip(kx, kg):
        ax.annotate(f"{y/1000:.0f}k", (x, y), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8)
    ax.set_ylabel("Gas per verification")
    ax.set_title("Gas vs K", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=8)

    ax = axes[0][1]
    ax.plot(tx, tg, "s-", color="#198038")
    sl, ic = fit(tx, tg)
    ax.plot(tx, [sl * x + ic for x in tx], "--", color="#999",
            label=f"fit: {sl:,.0f} gas/T ({abs(sl)/tg[0]*100:.2f}%/step)")
    if off_t:
        otx = sorted(off_t)
        ax2b = ax.twinx()
        ax2b.plot(otx, [off_t[t] for t in otx], "^--", color="#da1e28",
                  label="PSolve off-chain (ms)")
        ax2b.set_ylabel("PSolve time (ms)", color="#da1e28")
        ax2b.tick_params(axis="y", labelcolor="#da1e28")
    for x, y in zip(tx, tg):
        ax.annotate(f"{y/1000:.0f}k", (x, y), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8)
    ax.set_ylabel("Gas per verification")
    ax.set_title("Gas vs T", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=8, loc="upper left")

    # --- Row 2: fee (normalized) --------------------------------------------
    ax = axes[1][0]
    ax.plot(kx, kf, "o-", color="#0f62fe")
    sl, ic = fit(kx, kf)
    ax.plot(kx, [sl * x + ic for x in kx], "--", color="#999",
            label=f"fit: {sl:.1e} ETH/check")
    for x, y in zip(kx, kf):
        ax.annotate(f"{y:.1e}", (x, y), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8)
    ax.set_ylabel(f"ETH fee (@ {args.ref_gwei:g} gwei)")
    ax.set_title("Fee vs K (normalized)", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=8)

    ax = axes[1][1]
    ax.plot(tx, tf, "s-", color="#198038")
    sl, ic = fit(tx, tf)
    ax.plot(tx, [sl * x + ic for x in tx], "--", color="#999",
            label=f"fit: {sl:.1e} ETH/T")
    for x, y in zip(tx, tf):
        ax.annotate(f"{y:.1e}", (x, y), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8)
    usd = tf[-1] * args.eth_usd
    ax.set_ylabel(f"ETH fee (@ {args.ref_gwei:g} gwei)")
    ax.set_title("Fee vs T (normalized)", fontsize=11)
    ax.grid(alpha=0.3); ax.legend(fontsize=8)

    # --- Row 3: latency -------------------------------------------------------
    ax = axes[2][0]
    ax.plot(kx, kl, "o-", color="#9b59b6")
    for x, y in zip(kx, kl):
        ax.annotate(f"{y:.1f}s", (x, y), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8)
    ax.set_ylabel("submit → receipt (s)")
    ax.set_xlabel("K (spot checks; cheat prob 2^-K)")
    ax.set_title("Latency vs K — flat (block time dominates)", fontsize=11)
    ax.grid(alpha=0.3)

    ax = axes[2][1]
    ax.plot(tx, tl, "s-", color="#9b59b6")
    for x, y in zip(tx, tl):
        ax.annotate(f"{y:.1f}s", (x, y), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=8)
    ax.set_xlabel("T (time-lock length)")
    ax.set_title("Latency vs T — flat (T lives off-chain)", fontsize=11)
    ax.grid(alpha=0.3)

    fig.suptitle(
        f"Sepolia honest-verification metrics  "
        f"(latest session per point, Ethereum + Base Sepolia; "
        f"1 ETH = ${args.eth_usd:.0f})",
        fontsize=13)
    fig.tight_layout()

    out = EVM_ROOT / "bench" / "figures" / "sepolia" / "sepolia_metrics.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


def json_sessions() -> list[dict]:
    return json.loads(BENCH.read_text())


if __name__ == "__main__":
    main()
