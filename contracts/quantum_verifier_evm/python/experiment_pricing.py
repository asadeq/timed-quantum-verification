#!/usr/bin/env python3
"""
Bounty-pricing sweep: how the bounty level affects service and security.

For each pricing multiplier `lambda`, the client escrows

    bounty = lambda * (gasLeg + quote)

at fixed T and K, where `quote` is the server's published margin
(FeeQuoteRegistry) and `gasLeg` the client's gas reimbursement estimate. The
server applies its reservation rule — accept iff
`bounty >= quote + gasEstimate` — so:

  lambda < 1  -> refused: no solve, no submit; the client reclaims the escrow
  lambda >= 1 -> accepted: the claim verifies and the bounty pays atomically

Plotted against the forger's expected value `2^-K*bounty - gas` (which grows
with the bounty), the measured step at lambda = 1 gives the operating window:
below the reservation price no server serves you; above
`lambda* = 2^K * gas / B1` the bounty itself becomes worth attacking at the
chosen K. On a cheap chain the bounty is the attack surface; on an expensive
one the gas is.

Appends a session with `"experiment": "pricing"` to
`bench/commerce_ledger.json`; `plot_commerce.py` renders
`bench/figures/pricing_window.png` from it.

Usage (live, three funded cast keystores):
    export KEYSTORE_PASSWORD=...
    uv run python python/experiment_pricing.py \
        --rpc-url $BASE_SEPOLIA_RPC --verifier 0x.. --quote-from 0x.. \
        --accounts base-sep <server-keystore> <attacker-keystore> \
        --lambdas 0.6,0.8,0.9,1.0,1.1,1.5,2.0
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from experiment_commerce import (  # noqa: E402
    EST_BASE_GAS,
    EST_PER_CHECK_GAS,
    auth_for,
    balance_of,
    build_claim,
    make_puzzle,
    price_bounty,
    puzzle_commitment,
    puzzle_root,
    register,
    role_address,
    run,
    send,
    serialize_claim,
    server_margin,
)
from demo_eth import REASONS  # noqa: E402

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent
LEDGER = EVM_ROOT / "bench" / "commerce_ledger.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t", type=int, default=1)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rpc-url", required=True)
    ap.add_argument("--verifier", required=True)
    ap.add_argument("--quote-from", required=True,
                    help="FeeQuoteRegistry address (the server must have a quote)")
    ap.add_argument("--accounts", nargs=3, metavar=("CLIENT", "SERVER", "ATTACKER"),
                    default=["base-sep",
                             "c4355ac1-050e-4f38-9c41-a34014df4699",
                             "c5b534c2-f9a5-411c-bc0d-6bfbec76a47b"],
                    help="cast keystore names for client/server/attacker")
    ap.add_argument("--lambdas", default="0.6,0.8,0.9,1.0,1.1,1.5,2.0",
                    help="bounty multipliers over the fair price")
    ap.add_argument("--eth-usd", type=float, default=3000.0)
    args = ap.parse_args()
    args.accounts = dict(zip(("client", "server", "attacker"), args.accounts))

    rpc, verifier = args.rpc_url, args.verifier
    addrs = {role: role_address(role, args) for role in ("client", "server", "attacker")}
    for role, a in addrs.items():
        print(f"   {role:8s} {a}  {balance_of(a, rpc) / 1e18:.6f} ETH")

    chain_id = run(["cast", "chain-id", "--rpc-url", rpc], "chain-id")
    gas_price = int(run(["cast", "gas-price", "--rpc-url", rpc], "gas-price"))
    margin_wei, quote_src = server_margin(args, rpc, addrs["server"])
    est_gas = EST_BASE_GAS + EST_PER_CHECK_GAS * args.k
    fair = price_bounty(args.k, gas_price, margin_wei)      # gasLeg + quote
    reservation = margin_wei + est_gas * gas_price          # server's floor
    print(f"==> fair price (lambda=1): {fair / 1e18:.6f} ETH "
          f"[{quote_src}] @ {gas_price / 1e9:.2f} gwei; "
          f"server reservation {reservation / 1e18:.6f} ETH")

    lambdas = [float(x) for x in args.lambdas.split(",")]
    cycles: list[dict] = []
    ledger: list[dict] = []
    server20 = bytes.fromhex(addrs["server"].removeprefix("0x").lower())

    for lam in lambdas:
        print(f"\n== lambda = {lam}")
        bounty = int(fair * lam)
        tlp, pp, Z = make_puzzle(args.t)
        commitment = puzzle_commitment(tlp.embedded_message, 1, Z[1])
        root = puzzle_root(Z, solver=server20, commitment=commitment)
        pid = register("client", args, rpc, ledger, root, bounty)

        if bounty < reservation:
            print(f"   server REFUSES: bounty {bounty} < reservation {reservation}")
            client_before = balance_of(addrs["client"], rpc)
            send("client", args, rpc, ledger, "reclaim_bounty", None,
                 "reclaimBounty(uint32)", str(pid))
            cycles.append({
                "lambda": lam, "bounty_wei": bounty, "decision": "refused",
                "server_net_wei": 0,
                "client_cost_wei": client_before - balance_of(addrs["client"], rpc),
            })
            continue

        # accepted: solve, build the solver-bound claim, submit
        t0 = time.perf_counter()
        s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
        solve_ms = (time.perf_counter() - t0) * 1000
        non_reusable = sorted(witness["gate_keys"].keys())
        claim = build_claim(tlp, Z, witness, s, y, non_reusable[:args.k],
                            solver=server20, commitment=commitment)
        assert claim["puzzle_hash"] == root
        server_before = balance_of(addrs["server"], rpc)
        row = send("server", args, rpc, ledger, "verify_honest", None,
                   "submitAndVerify(uint32,bytes)", str(pid),
                   f"0x{serialize_claim(claim).hex()}")
        paid = row["balance_after_wei"] - server_before + row["gas_cost_wei"]
        ok = row.get("verdict") == "verified"
        print(f"   server {'VERIFIED' if ok else 'FAILED'}: net "
              f"{(paid - row['gas_cost_wei']) / 1e18:.8f} ETH, solve {solve_ms:.0f}ms")
        cycles.append({
            "lambda": lam, "bounty_wei": bounty,
            "decision": "accepted" if ok else "failed",
            "server_net_wei": paid - row["gas_cost_wei"],
            "gas_cost_wei": row["gas_cost_wei"],
            "client_cost_wei": bounty + (ledger[-2]["gas_cost_wei"]
                                         if len(ledger) >= 2 else 0),
        })

    summary = {
        "venue": f"sepolia-{chain_id}", "chain_id": chain_id, "rpc": rpc,
        "verifier": verifier, "quote_registry": args.quote_from,
        "addrs": addrs, "eth_usd": args.eth_usd,
        "experiment": "pricing",
        "params": {"T": args.t, "K": args.k, "gas_price_wei": gas_price,
                   "fair_wei": fair, "quote_wei": margin_wei,
                   "est_gas": est_gas, "lambdas": lambdas},
        "cycles": cycles, "steps": ledger,
    }
    sessions = json.loads(LEDGER.read_text()) if LEDGER.exists() else []
    sessions.append(summary)
    LEDGER.write_text(json.dumps(sessions, indent=1))
    print(f"\n==> appended pricing session to {LEDGER} "
          f"({sum(1 for c in cycles if c['decision'] == 'accepted')}/"
          f"{len(cycles)} accepted)")


if __name__ == "__main__":
    main()
