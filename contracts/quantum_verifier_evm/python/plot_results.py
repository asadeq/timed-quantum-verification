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

    # ---- 1c. Sepolia 2x2 (gas AND fee, vs K and T): gas AND fee vs K AND T ---------------------------
    # Fee is what a user actually pays (gas price fluctuates per block), so
    # the per-parameter curves should show it alongside gas. Latency is left
    # off these curves deliberately: each sweep point is 1-2 samples and
    # Sepolia's ~12s block time dominates, so error bars would be larger than
    # the signal — per-venue latency lives in honest_metrics.png instead.
    sep = [s for s in sessions if short_venue(s) == "sepolia"]
    if sep:
        agg: dict[str, dict[int, dict[str, list[float]]]] = {
            "K": defaultdict(lambda: defaultdict(list)),
            "T": defaultdict(lambda: defaultdict(list)),
        }
        fee_scatter: list[tuple[float, float]] = []  # (basefee gwei, paid fee ETH)
        off_t: dict[int, float] = {}
        REF_GWEI = 1.0  # reference gas price for normalized fee curves
        for s in sep:
            k = s.get("params", {}).get("K", 8)
            t = s.get("params", {}).get("T", 1)
            for r in s["runs"]:
                if not r["name"].startswith("verify_honest"):
                    continue
                gas = r["gas_used"]
                eff_wei = r.get("effective_gas_price_wei", 0)
                basefee_gwei = (eff_wei / 1e9) if eff_wei else 0.0
                agg["K"][k]["gas"].append(gas)
                agg["K"][k]["fee_ref"].append(gas * REF_GWEI / 1e9)  # ETH @ ref
                agg["T"][t]["gas"].append(gas)
                agg["T"][t]["fee_ref"].append(gas * REF_GWEI / 1e9)
                if basefee_gwei > 0:
                    fee_scatter.append((basefee_gwei, gas * basefee_gwei / 1e18))
            oc = s.get("offchain_ms", {})
            if oc and t not in off_t:
                off_t[t] = oc.get("psolve_ms", 0.0)

        def mean_series(d: dict[int, dict[str, list]], key: str) -> tuple[list, list]:
            xs = sorted(d)
            return xs, [sum(d[x][key]) / len(d[x][key]) for x in xs]

        kx, kg = mean_series(agg["K"], "gas")
        tx, tg = mean_series(agg["T"], "gas")
        _, kf_ref = mean_series(agg["K"], "fee_ref")
        _, tf_ref = mean_series(agg["T"], "fee_ref")

        fig, axes = plt.subplots(2, 2, figsize=(12, 8))
        panels = [
            (axes[0][0], kx, kg, "Gas vs K", "K (spot checks; cheat prob 2^-K)",
             "o-", "#0f62fe", "gas", "~29.8k gas per extra spot check"),
            (axes[0][1], tx, tg, "Gas vs T", "T (time-lock length)",
             "s-", "#198038", "gas", None),
            (axes[1][0], kx, kf_ref, "Fee vs K (normalized @ 1 gwei)",
             "K (spot checks)", "o-", "#0f62fe", "fee_ref",
             "fee = gas x price; price held fixed"),
            (axes[1][1], tx, tf_ref, "Fee vs T (normalized @ 1 gwei)",
             "T (time-lock length)", "s-", "#198038", "fee_ref", None),
        ]
        for ax, xs, ys, title, xlabel, style, color, kind, note in panels:
            ax.plot(xs, ys, style, color=color)
            if len(xs) >= 2:
                n = len(xs)
                sx, sy = sum(xs), sum(ys)
                sxy = sum(x * y for x, y in zip(xs, ys))
                sxx = sum(x * x for x in xs)
                slope = (n * sxy - sx * sy) / (n * sxx - sx * sx)
                icpt = (sy - slope * sx) / n
                unit = "gas/step" if kind == "gas" else f"ETH/step @ {REF_GWEI:g} gwei"
                label = f"fit: {slope:,.0f} {unit}" if kind == "gas" \
                    else f"fit: {slope:.2e} {unit}"
                ax.plot(xs, [slope * x + icpt for x in xs], "--",
                        color="#999", label=label)
                if "vs T" in title and kind == "gas":
                    # annotate the drift's cause honestly
                    ax.annotate("drift = bitmap header growth\n"
                                "(ceil(max_gate/8) bytes; NOT verify logic)",
                                xy=(xs[-1], ys[-1]), xytext=(-140, 10),
                                textcoords="offset points", fontsize=8,
                                arrowprops=dict(arrowstyle="->", color="#666"))
                ax.legend(fontsize=8)
            for x, y in zip(xs, ys):
                fmt = f"{y/1000:.0f}k" if kind == "gas" else f"{y:.1e}"
                ax.annotate(fmt, (x, y), textcoords="offset points",
                            xytext=(0, 6), ha="center", fontsize=7)
            ax.set_xlabel(xlabel)
            ax.set_ylabel("ETH @ 1 gwei" if kind == "fee_ref" else "Gas")
            ax.set_title(title, fontsize=11)
            ax.grid(alpha=0.3)
        if off_t:
            otx = sorted(off_t)
            axes[0][1].plot(otx, [off_t[t] for t in otx], "^--", color="#da1e28",
                            label="PSolve off-chain (ms) — grows linearly")
            axes[0][1].legend(fontsize=8)
        fig.suptitle("Live Sepolia verification cost (verifier 0xB40d…b0F5)",
                     fontsize=12)
        fig.tight_layout()
        fig.savefig(out_dir / "sepolia_constant_cost.png", dpi=150)
        print(f"wrote {out_dir / 'sepolia_constant_cost.png'} "
              f"(K: {kx}, T: {tx})")

        # ---- fee volatility: paid fee tracks the market, not the protocol ---
        if len(fee_scatter) >= 3:
            fig2, ax = plt.subplots(figsize=(7, 4.5))
            bf, fee = zip(*sorted(fee_scatter))
            ax.scatter(bf, fee, color="#0f62fe", s=40)
            # reference line: fee for the median-K gas at each basefee
            ref_gas = 303_000  # K=8 anchor
            import numpy as _np
            xs_line = _np.linspace(min(bf), max(bf), 50)
            ax.plot(xs_line, [g * p / 1e18 for g, p in
                              zip([ref_gas] * len(xs_line), xs_line)],
                    "--", color="#da1e28",
                    label=f"gas x price at {ref_gas:,} gas (K=8)")
            ax.set_xlabel("Block effective gas price (gwei)")
            ax.set_ylabel("Paid fee (ETH)")
            ax.set_title("Paid fee tracks the market, not the protocol\n"
                         "(same K=8 gas — fee varies with Sepolia base fee)")
            ax.grid(alpha=0.3)
            ax.legend(fontsize=9)
            fig.tight_layout()
            fig.savefig(out_dir / "fee_volatility.png", dpi=150)
            print(f"wrote {out_dir / 'fee_volatility.png'}")
    else:
        print("sepolia panel: no sessions with venue 'sepolia' yet")

    # ---- 1e. Latency vs K and vs T, per venue ------------------------------
    # Expected result: latency is INDEPENDENT of K and T (the contract does
    # ~300k gas of work; inclusion time dominates), and scales with the
    # venue's block cadence (anvil instant, Sepolia ~12s). Panels use median
    # + IQR whiskers because latency is heavy-tailed (a tx that just missed
    # a block waits a full interval).
    lat: dict[str, dict[str, dict[int, list[float]]]] = {
        "K": defaultdict(lambda: defaultdict(list)),
        "T": defaultdict(lambda: defaultdict(list)),
    }
    for s in sessions:
        v = short_venue(s)
        k = s.get("params", {}).get("K", 8)
        t = s.get("params", {}).get("T", 1)
        for r in s["runs"]:
            if not r["name"].startswith("verify_honest"):
                continue
            lat["K"][v][k].append(r["latency_ms"] / 1000)
            lat["T"][v][t].append(r["latency_ms"] / 1000)

    def _median_plot(ax, per_venue, xlabel, title):
        for v, per_x in sorted(per_venue.items()):
            xs = sorted(per_x)
            med = [st.median(per_x[x]) for x in xs]
            q1 = [st.quantiles(per_x[x], n=4)[0] if len(per_x[x]) >= 4 else med[i]
                  for i, x in enumerate(xs)]
            q3 = [st.quantiles(per_x[x], n=4)[2] if len(per_x[x]) >= 4 else med[i]
                  for i, x in enumerate(xs)]
            ax.plot(xs, med, "o-", label=f"{v} (median, n={len(per_x[x])})")
            ax.fill_between(xs, q1, q3, alpha=0.2)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("submit → receipt (s)")
        ax.set_title(title, fontsize=11)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)

    if any(per_x for per_x in lat["K"].values() if per_x):
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.5))
        _median_plot(ax1, lat["K"], "K (spot checks)",
                     "Latency vs K — flat: inclusion time dominates")
        _median_plot(ax2, lat["T"], "T (time-lock length)",
                     "Latency vs T — flat: T lives off-chain")
        fig.suptitle("Time-to-verdict is independent of the claim's parameters",
                     fontsize=12)
        fig.tight_layout()
        fig.savefig(out_dir / "latency_sweeps.png", dpi=150)
        print(f"wrote {out_dir / 'latency_sweeps.png'}")


if __name__ == "__main__":
    main()
