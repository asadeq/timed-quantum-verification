#!/usr/bin/env python3
"""Publish the quantum server's price quote to the FeeQuoteRegistry.

The server's margin per verified claim is its labor price for the sequential
PSolve work. The client reads it (`quoteOf`) before escrowing the bounty at
`QuantumVerifier.registerPuzzle` — the server quotes, the client escrows, the
server accepts by solving.

Usage (server's keystore):
    export KEYSTORE_PASSWORD=...
    uv run python python/publish_quotes.py \
        --registry 0x... --account base-sep --rpc-url $BASE_SEPOLIA_RPC \
        --margin-usd 0.50 --eth-usd 3000
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent

_FOUNDRY_BIN = Path.home() / ".foundry" / "bin"
if _FOUNDRY_BIN.is_dir():
    os.environ["PATH"] = str(_FOUNDRY_BIN) + os.pathsep + os.environ.get("PATH", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", required=True, help="FeeQuoteRegistry address")
    ap.add_argument("--account", required=True,
                    help="cast keystore name of the SERVER account")
    ap.add_argument("--rpc-url", required=True)
    ap.add_argument("--margin-usd", type=float, default=0.50,
                    help="server labor price per verified claim, USD")
    ap.add_argument("--eth-usd", type=float, default=3000.0)
    args = ap.parse_args()

    password = os.environ.get("KEYSTORE_PASSWORD")
    if not password:
        raise SystemExit("KEYSTORE_PASSWORD not set (non-interactive cast needs it)")

    wei = int(args.margin_usd / args.eth_usd * 1e18)
    print(f"==> publishing quote: {wei} wei/claim "
          f"(${args.margin_usd:.2f} @ ETH=${args.eth_usd:.0f})")

    proc = subprocess.run(
        ["cast", "send", args.registry, "setQuote(uint96)", str(wei),
         "--account", args.account, "--password", password,
         "--rpc-url", args.rpc_url, "--json"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr[-2000:])
        raise SystemExit("setQuote failed")
    import json
    rec = json.loads(proc.stdout)
    print(f"    tx {rec.get('transactionHash')}  status {rec.get('status')}")

    out = subprocess.run(
        ["cast", "call", args.registry, "quoteOf(address)(uint96)",
         "0x" + subprocess.run(
             ["cast", "wallet", "address", "--account", args.account,
              "--password", password],
             capture_output=True, text=True).stdout.strip().splitlines()[-1]
             .removeprefix("0x"),
         "--rpc-url", args.rpc_url],
        capture_output=True, text=True,
    )
    readback = int(out.stdout.strip().splitlines()[-1].split()[0], 0)
    assert readback == wei, f"readback mismatch: {readback} != {wei}"
    print(f"==> confirmed: quoteOf(server) = {readback} wei "
          f"({readback / 1e18:.6f} ETH)")


if __name__ == "__main__":
    main()
