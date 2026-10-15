#!/usr/bin/env python3
"""
Generate the value-proposition figures from bench/evm_results.json (+ optional
Python baseline timings). Outputs PNG plots and a markdown summary table.

Figures:
  1. frontier.png      — gas vs cheating probability (2^-K): the
                         security-per-cost frontier of on-chain verification.
  2. constant_cost.png — verification gas vs T (off-chain work): demonstrates
                         the on-chain cost is ~constant in the puzzle's
                         time-lock length, the protocol's headline claim.
  3. compare.png       — on-chain vs Python-only verification cost in USD,
                         when a Python baseline JSON is provided.

Usage:
    uv run python python/plot_results.py
    uv run python python/plot_results.py --python-baseline pv_baseline.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

EVM_ROOT = Path(__file__).resolve().parent.parent
BENCH = EVM_ROOT / "bench" / "evm_results.json"


def load_sessions() -> list[dict]:
    if not BENCH.exists():
        raise SystemExit(f"{BENCH} not found — run demo_eth.py --benchmark first")
    return json.loads(BENCH.read_text())


# Map chain ids to short, plot-friendly venue names; anything with an explicit
# --venue-label already has one, and legacy sessions recorded a raw URL.
CHAIN_NAMES = {"31337": "anvil", "11155111": "sepolia", "84532": "base-sepolia"}


def short_venue(session: dict) -> str:
    v = session.get("venue", "?")
    if v.startswith("http"):
        cid = str(session.get("chain_id", ""))
        return CHAIN_NAMES.get(cid, f"chain-{cid}")
    return v


def honest_gas_by_k(sessions: list[dict]) -> dict[int, list[int]]:
    """{K: [gas, ...]} averaged across all sessions."""
    by_k: dict[int, list[int]] = defaultdict(list)
    for s in sessions:
        for r in s["runs"]:
            if r["name"].startswith("verify_honest"):
                k = s.get("params", {}).get("K", 8)
                by_k[k].append(r["gas_used"])
    return by_k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python-baseline", default=None,
                    help="JSON with {'K': int, 'pverify_ms': float} entries "
                         "for the Python-only verifier comparison")
    ap.add_argument("--eth-usd", type=float, default=3000.0,
                    help="ETH price for USD figures (annotate on plots)")
    args = ap.parse_args()

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise SystemExit("pip install matplotlib to generate figures")

    sessions = load_sessions()
    out_dir = EVM_ROOT / "bench" / "figures"
    out_dir.mkdir(exist_ok=True)

    # ---- 1. Security/cost frontier ----------------------------------------
    by_k = honest_gas_by_k(sessions)
    ks = sorted(by_k)
    if len(ks) >= 2:
        gas_avg = [sum(by_k[k]) / len(by_k[k]) for k in ks]
        cheat = [2.0 ** (-k) for k in ks]

        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.plot(cheat, gas_avg, "o-", color="#0f62fe")
        for k, g, c in zip(ks, gas_avg, cheat):
            ax.annotate(f"K={k}", (c, g), textcoords="offset points", xytext=(6, 4))
        ax.set_xscale("log")
        ax.set_xlabel("Cheating probability (2^-K) — lower is better")
        ax.set_ylabel("Gas per verification (avg over runs)")
        ax.set_title("Security-per-cost frontier of on-chain TLP verification")
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "frontier.png", dpi=150)
        print(f"wrote {out_dir / 'frontier.png'}")
    else:
        print("frontier: need >=2 distinct K values (run sweep_k.py)")

    # ---- 2. Constant cost in T ---------------------------------------------
    # Sessions carry params.T; group honest gas by T.
    by_t: dict[int, list[int]] = defaultdict(list)
    for s in sessions:
        t = s.get("params", {}).get("T", 1)
        for r in s["runs"]:
            if r["name"].startswith("verify_honest"):
                by_t[t].append(r["gas_used"])
    if len(by_t) >= 2:
        ts = sorted(by_t)
        gas = [sum(by_t[t]) / len(by_t[t]) for t in ts]
        fig, ax = plt.subplots(figsize=(7, 4.5))
        ax.plot(ts, gas, "s-", color="#198038", label="on-chain verify (gas)")
        ax.set_xlabel("Time-lock length T (sequential SHA-256 steps)")
        ax.set_ylabel("Gas per verification")
        ax.set_title("On-chain verification cost is constant in T")
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out_dir / "constant_cost.png", dpi=150)
        print(f"wrote {out_dir / 'constant_cost.png'}")
    else:
        print("constant_cost: need sessions with >=2 distinct T values "
              "(run demo_eth.py --T 1 / --T 10 / --T 50 ... --benchmark)")

    # ---- 3. On-chain vs Python comparison ----------------------------------
    if args.python_baseline:
        base = json.loads(Path(args.python_baseline).read_text())
        rows = base if isinstance(base, list) else base.get("results", [])
        k8 = next((r for r in rows if r.get("K") == 8), rows[0] if rows else None)
        if k8 and "pverify_ms" in k8:
            # Use the latest live-network session for fee comparison.
            live = [s for s in sessions if "chain-" in s.get("venue", "")] or sessions
            last = live[-1]
            honest = [r for r in last["runs"] if r["name"].startswith("verify_honest")]
            fee_eth = sum(r["fee_wei"] for r in honest) / len(honest) / 1e18
            usd = fee_eth * args.eth_usd

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4.5))
            ax1.bar(["Python-only", "On-chain"], [k8["pverify_ms"] / 1000, last["runs"][1]["latency_ms"] / 1000],
                    color=["#8d8d8d", "#0f62fe"])
            ax1.set_ylabel("verification time (s)")
            ax1.set_title("Wall-clock per verification")
            ax2.bar(["Python-only", "On-chain"], [0.0, usd], color=["#8d8d8d", "#0f62fe"])
            ax2.set_ylabel(f"cost (USD @ {args.eth_usd:.0f}/ETH)")
            ax2.set_title("Cost per verification")
            fig.suptitle("Why on-chain verification: trust for ~$%.5f/claim" % usd)
            fig.tight_layout()
            fig.savefig(out_dir / "compare.png", dpi=150)
            print(f"wrote {out_dir / 'compare.png'}")
        else:
            print("python baseline missing pverify_ms/K fields")
    else:
        print("compare: pass --python-baseline to include the Python-only column")

    # ---- 1b. Honest-claims value panel (gas / fee / latency per venue) ------
    by_venue: dict[str, dict] = {}
    for s in sessions:
        v = short_venue(s)
        b = by_venue.setdefault(v, {"gas": [], "fee": [], "lat": []})
        for r in s["runs"]:
            if r["name"].startswith("verify_honest"):
                b["gas"].append(r["gas_used"])
                b["fee"].append(r["fee_wei"] / 1e18)
                b["lat"].append(r["latency_ms"] / 1000)
    if by_venue:
        import statistics as st
        venues = list(by_venue)
        means = {
            "gas": [st.mean(by_venue[v]["gas"]) / 1000 for v in venues],       # k-gas
            "fee": [st.mean(by_venue[v]["fee"]) * 1e5 for v in venues],        # 1e-5 ETH
            "lat": [st.mean(by_venue[v]["lat"]) for v in venues],
        }
        stds = {
            "gas": [(st.stdev(by_venue[v]["gas"]) if len(by_venue[v]["gas"]) > 1 else 0) / 1000
                    for v in venues],
        }
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))
        colors = ["#0f62fe"] + ["#8d8d8d"] * (len(venues) - 1)
        specs = [
            ("gas", "Gas per honest verification (×1000)", "{:.1f}k"),
            ("fee", "ETH fee per honest verification (×10⁻⁵)", "{:.2f}"),
            ("lat", "Submit → receipt latency (s)", "{:.1f}s"),
        ]
        for ax, (key, title, fmt) in zip(axes, specs):
            vals = means[key]
            bars = ax.bar(venues, vals, color=colors, width=0.55)
            if key == "gas":
                ax.errorbar(venues, vals, yerr=stds["gas"], fmt="none",
                            ecolor="black", capsize=4)
            ax.set_title(title, fontsize=11)
            ax.grid(alpha=0.3, axis="y")
            for bar, v in zip(bars, vals):
                ax.annotate(fmt.format(v),
                            (bar.get_x() + bar.get_width() / 2, bar.get_height()),
                            ha="center", va="bottom", fontsize=9)
            ax.set_ylim(0, max(vals) * 1.25)
        fig.suptitle("Honest verification cost by venue "
                     f"(mean over runs; 1 ETH = ${args.eth_usd:.0f})", fontsize=12)
        fig.tight_layout()
        fig.savefig(out_dir / "honest_metrics.png", dpi=150)
        print(f"wrote {out_dir / 'honest_metrics.png'}")

    # ---- 1c. Sepolia constant-cost curves: gas vs K, and gas vs T ----------
    # One panel per axis, per venue, so the "linear in K / flat in T" story is
    # visible on live-network data, not just anvil.
    sep = [s for s in sessions if short_venue(s) == "sepolia"]
    if sep:
        k_gas: dict[int, list[int]] = defaultdict(list)
        t_gas: dict[int, list[int]] = defaultdict(list)
        for s in sep:
            k = s.get("params", {}).get("K", 8)
            t = s.get("params", {}).get("T", 1)
            for r in s["runs"]:
                if r["name"].startswith("verify_honest"):
                    k_gas[k].append(r["gas_used"])
                    t_gas[t].append(r["gas_used"])
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
        # gas vs K
        ks = sorted(k_gas)
        m = [st := sum(k_gas[k]) / len(k_gas[k]) for k in ks]
        fit_slope = None
        if len(ks) >= 2:
            n = len(ks)
            sx, sy = sum(ks), sum(m)
            sxy = sum(k * y for k, y in zip(ks, m))
            sxx = sum(k * k for k in ks)
            fit_slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
            intercept = (sy - fit_slope * sx) / n
        ax1.plot(ks, m, "o-", color="#0f62fe")
        ax1.plot(ks, [fit_slope * k + intercept for k in ks], "--", color="#999",
                 label=f"fit: {fit_slope:,.0f} gas/K")
        for k, y in zip(ks, m):
            ax1.annotate(f"{y/1000:.0f}k", (k, y), textcoords="offset points",
                         xytext=(0, 6), ha="center", fontsize=8)
        ax1.set_xlabel("K (spot checks) — cheating prob 2^-K")
        ax1.set_ylabel("Gas per verification")
        ax1.set_title("Sepolia: gas vs K (linear)")
        ax1.grid(alpha=0.3)
        ax1.legend(fontsize=9)
        # gas vs T
        ts = sorted(t_gas)
        mt = [sum(t_gas[t]) / len(t_gas[t]) for t in ts]
        ax2.plot(ts, mt, "s-", color="#198038")
        if len(ts) >= 2:
            n = len(ts)
            sx, sy = sum(ts), sum(mt)
            sxy = sum(t * y for t, y in zip(ts, mt))
            sxx = sum(t * t for t in ts)
            t_slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
            ax2.plot(ts, [t_slope * t + (sy - t_slope * sx) / n for t in ts],
                     "--", color="#999", label=f"fit: {t_slope:,.0f} gas/T")
        for t, y in zip(ts, mt):
            ax2.annotate(f"{y/1000:.0f}k", (t, y), textcoords="offset points",
                         xytext=(0, 6), ha="center", fontsize=8)
        ax2.set_xlabel("T (time-lock length)")
        ax2.set_ylabel("Gas per verification")
        ax2.set_title("Sepolia: gas vs T (constant)")
        ax2.grid(alpha=0.3)
        ax2.legend(fontsize=9)
        fig.suptitle("Live Sepolia verification cost", fontsize=12)
        fig.tight_layout()
        fig.savefig(out_dir / "sepolia_constant_cost.png", dpi=150)
        print(f"wrote {out_dir / 'sepolia_constant_cost.png'} "
              f"(K values: {ks}, T values: {ts})")
    else:
        print("sepolia panel: no sessions with venue 'sepolia' yet")

    # ---- Markdown summary ---------------------------------------------------
    lines = ["# Benchmark summary", ""]
    for s in sessions:
        lines.append(f"## {s.get('venue')} — {s.get('timestamp_utc', '?')} "
                     f"(T={s.get('params', {}).get('T')}, K={s.get('params', {}).get('K')})")
        lines.append("| op | gas | fee ETH | latency s |")
        lines.append("|---|---|---|---|")
        for r in s["runs"]:
            lines.append(f"| {r['name']} | {r['gas_used']:,} | "
                         f"{r['fee_wei'] / 1e18:.8f} | {r['latency_ms'] / 1000:.1f} |")
        if "offchain_ms" in s:
            oc = s["offchain_ms"]
            lines.append("")
            lines.append(f"off-chain: PSetup {oc['psetup_garble_ms']:.0f} ms · "
                         f"PGen {oc['pgen_ms']:.0f} ms · PSolve {oc['psolve_ms']:.0f} ms · "
                         f"claim-build {oc['claim_build_ms']:.1f} ms")
        lines.append("")
    summary = out_dir / "summary.md"
    summary.write_text("\n".join(lines))
    print(f"wrote {summary}")


if __name__ == "__main__":
    main()
