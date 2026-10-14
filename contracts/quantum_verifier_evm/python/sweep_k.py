#!/usr/bin/env python3
"""
Sweep driver for benchmarking the EVM verifier across K (spot-check count).

Runs the demo once per K value against a deployed verifier, collecting gas,
fee, and latency into bench/evm_results.json with distinct venue labels per
sweep, so the security-vs-cost frontier (gas grows linearly in K while
cheating probability falls as 2^-K) can be plotted straight from the file.

Security note baked into the data: each claim row's `cheat_probability` is
2^-K — the "security" axis of the frontier plot.

Usage (local):
    export PATH="$HOME/.foundry/bin:$PATH"
    uv run python python/sweep_k.py                       # anvil, K=1..16

Live (already-funded keystore, already-deployed verifier):
    export $(grep -v '^#' .env | xargs)
    uv run python python/sweep_k.py --rpc-url $ETH_SEPOLIA_RPC \
        --account base-sep --verifier 0x70bA...823e5 --venue-label sepolia
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent

# Make foundry reachable if the user forgot to export PATH.
_FOUNDRY_BIN = Path.home() / ".foundry" / "bin"
if _FOUNDRY_BIN.is_dir():
    import os
    os.environ["PATH"] = str(_FOUNDRY_BIN) + os.pathsep + os.environ.get("PATH", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k-values", default="1,2,4,8,16",
                    help="comma-separated K values to sweep")
    ap.add_argument("--repeat", type=int, default=1,
                    help="honest submissions per K (for averaging)")
    ap.add_argument("--rpc-url", default=None)
    ap.add_argument("--account", default=None)
    ap.add_argument("--private-key", default=None)
    ap.add_argument("--verifier", default=None)
    ap.add_argument("--venue-label", default=None)
    ap.add_argument("--benchmark", action="store_true", default=True)
    args = ap.parse_args()

    ks = [int(k) for k in args.k_values.split(",")]
    print(f"==> K sweep over {ks}, repeat={args.repeat}")

    for k in ks:
        print(f"\n{'=' * 60}\n== K = {k}\n{'=' * 60}")
        cmd = [
            sys.executable, str(HERE / "demo_eth.py"),
            "--spot-checks", str(k),
            "--repeat", str(args.repeat),
            "--benchmark",
        ]
        if args.rpc_url:
            cmd += ["--rpc-url", args.rpc_url]
        if args.account:
            cmd += ["--account", args.account]
        if args.private_key:
            cmd += ["--private-key", args.private_key]
        if args.verifier:
            cmd += ["--verifier", args.verifier]
        if args.venue_label:
            cmd += ["--venue-label", args.venue_label]

        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            print(f"!! K={k} failed (exit {proc.returncode}) — continuing with next K")

    # Summarize what we just collected.
    out = EVM_ROOT / "bench" / "evm_results.json"
    sessions = json.loads(out.read_text()) if out.exists() else []
    sweep = [s for s in sessions
             if s.get("params", {}).get("K") in ks
             and (args.venue_label or "") in s.get("venue", "")
             or (args.venue_label is None and s.get("params", {}).get("K") in ks)]
    print(f"\n==> Sweep complete. {len(sessions)} sessions total in {out}")
    for s in sessions:
        p = s.get("params", {})
        if not p:
            continue  # legacy sessions without a params block
        honest = [r for r in s["runs"] if r["name"].startswith("verify_honest")]
        if honest:
            gas = sum(r["gas_used"] for r in honest) // len(honest)
            print(f"   K={p['K']:2d}  venue={s['venue'][:28]:28s}  "
                  f"honest gas avg {gas:8,d}  cheat prob 2^-{p['K']}")


if __name__ == "__main__":
    main()
