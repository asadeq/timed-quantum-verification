#!/usr/bin/env python3
"""
Sweep driver for benchmarking the EVM verifier across T (time-lock length).

For each T, runs demo_eth.py with --repeat R so the gas-vs-T figure has
mean ± std error bars instead of single-sample noise. Complements sweep_k.py
(K axis / security frontier); together they produce the paper's two headline
plots:

  - gas vs T   (should be FLAT: on-chain cost is constant in time-lock length)
  - gas vs K   (linear: the security dial has a quoted price)

Usage (local anvil):
    export PATH="$HOME/.foundry/bin:$PATH"
    uv run python python/sweep_t.py --t-values 1,10,25,50,100 --repeat 10

Live:
    export $(grep -v '^#' .env | xargs)
    uv run python python/sweep_t.py --t-values 1,10,25,50 --repeat 5 \
        --rpc-url $ETH_SEPOLIA_RPC --account base-sep \
        --verifier 0x70bA...823e5 --venue-label sepolia
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent

_FOUNDRY_BIN = Path.home() / ".foundry" / "bin"
if _FOUNDRY_BIN.is_dir():
    import os
    os.environ["PATH"] = str(_FOUNDRY_BIN) + os.pathsep + os.environ.get("PATH", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t-values", default="1,10,25,50,100",
                    help="comma-separated T values to sweep")
    ap.add_argument("--repeat", type=int, default=10,
                    help="honest submissions per T (error bars need >=5)")
    ap.add_argument("--spot-checks", type=int, default=8,
                    help="K held fixed across the sweep (default 8)")
    ap.add_argument("--rpc-url", default=None)
    ap.add_argument("--account", default=None)
    ap.add_argument("--private-key", default=None)
    ap.add_argument("--verifier", default=None)
    ap.add_argument("--venue-label", default=None)
    args = ap.parse_args()

    ts = [int(t) for t in args.t_values.split(",")]
    print(f"==> T sweep over {ts}, repeat={args.repeat}, K={args.spot_checks}")

    for t in ts:
        print(f"\n{'=' * 60}\n== T = {t}\n{'=' * 60}")
        cmd = [
            sys.executable, str(HERE / "demo_eth.py"),
            "--T", str(t),
            "--spot-checks", str(args.spot_checks),
            "--repeat", str(args.repeat),
            "--benchmark",
        ]
        for flag, val in [("--rpc-url", args.rpc_url), ("--account", args.account),
                          ("--private-key", args.private_key),
                          ("--verifier", args.verifier),
                          ("--venue-label", args.venue_label)]:
            if val:
                cmd += [flag, val]

        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            print(f"!! T={t} failed (exit {proc.returncode}) — continuing")

    # ---- Summary: per-T stats over all matching sessions --------------------
    out = EVM_ROOT / "bench" / "evm_results.json"
    sessions = json.loads(out.read_text()) if out.exists() else []

    by_t: dict[int, list[int]] = {}
    for s in sessions:
        p = s.get("params")
        if not p or p.get("K") != args.spot_checks:
            continue
        if args.venue_label and s.get("venue") != args.venue_label:
            continue
        if not args.venue_label and s.get("venue", "").startswith("chain-"):
            continue  # local sweep only, unless labeled
        for r in s["runs"]:
            if r["name"].startswith("verify_honest"):
                by_t.setdefault(p["T"], []).append(r["gas_used"])

    print(f"\n==> T sweep summary (K={args.spot_checks}, "
          f"{'n samples per T' }):")
    print(f"{'T':>5} {'n':>3} {'mean gas':>12} {'std':>8} {'min':>12} {'max':>12}")
    import statistics
    for t in sorted(by_t):
        g = by_t[t]
        print(f"{t:5d} {len(g):3d} {statistics.mean(g):12,.0f} "
              f"{statistics.stdev(g) if len(g) > 1 else 0:8,.0f} "
              f"{min(g):12,d} {max(g):12,d}")

    if len(by_t) >= 2:
        ts_sorted = sorted(by_t)
        slope, intercept = statistics.linear_regression(
            ts_sorted, [statistics.mean(by_t[t]) for t in ts_sorted]).slope, None
        fit = statistics.linear_regression(
            ts_sorted, [statistics.mean(by_t[t]) for t in ts_sorted])
        print(f"\nlinear fit: gas = {fit.slope:.3f} * T + {fit.intercept:,.0f}")
        per_T_pct = abs(fit.slope) / statistics.mean(by_t[ts_sorted[0]]) * 100
        print(f"slope as % of baseline per T-step: {per_T_pct:.4f}% "
              f"({'FLAT — constant-cost claim holds' if per_T_pct < 0.1 else 'check for drift'})")


if __name__ == "__main__":
    main()
