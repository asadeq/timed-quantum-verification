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


def honest_gas_by_k(sessions: list[dict]) -> dict[int, list[int]]:
    """venue -> {K: [gas, ...]} averaged across all sessions."""
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
    # Groups ALL honest verification runs by venue and shows the three metrics
    # a user cares about: deterministic cost (gas), price paid (ETH), and
    # time-to-verdict (latency).
    by_venue: dict[str, dict] = {}
    for s in sessions:
        v = s.get("venue", "?")
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
            "gas": [st.mean(by_venue[v]["gas"]) for v in venues],
            "fee": [st.mean(by_venue[v]["fee"]) for v in venues],
            "lat": [st.mean(by_venue[v]["lat"]) for v in venues],
        }
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.5))
        colors = ["#0f62fe"] + ["#8d8d8d"] * (len(venues) - 1)
        specs = [
            ("gas", "Gas per honest verification", "{:,.0f}", 1000),
            ("fee", "ETH fee per honest verification", "{:.8f}", 1),
            ("lat", "Submit → receipt latency (s)", "{:.1f}", 1000),
        ]
        for ax, (key, title, fmt, div) in zip(axes, specs):
            vals = [m / div for m in means[key]]
            bars = ax.bar(venues, vals, color=colors)
            ax.set_title(title)
            ax.grid(alpha=0.3, axis="y")
            # annotate bars; rotate labels when venue names are long
            for bar, v in zip(bars, vals):
                label = fmt.format(v)
                if len(venues) > 2:
                    ax.annotate(label, (bar.get_x() + bar.get_width() / 2, v),
                                ha="center", va="bottom", fontsize=8, rotation=45)
                else:
                    ax.annotate(label, (bar.get_x() + bar.get_width() / 2, v),
                                ha="center", va="bottom")
            if len(venues) > 2:
                ax.tick_params(axis="x", rotation=30)
        # std as error bar on gas (the deterministic metric)
        axes[0].errorbar(range(len(venues)), [m / 1000 for m in means["gas"]],
                         yerr=[(st.stdev(by_venue[v]["gas"]) if len(by_venue[v]["gas"]) > 1 else 0) / 1000
                               for v in venues], fmt="none", ecolor="black", capsize=4)
        fig.suptitle("Honest verification cost by venue (mean over runs; "
                     f"1 ETH = ${args.eth_usd:.0f})")
        fig.tight_layout()
        fig.savefig(out_dir / "honest_metrics.png", dpi=150)
        print(f"wrote {out_dir / 'honest_metrics.png'}")

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
