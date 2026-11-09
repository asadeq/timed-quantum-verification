#!/usr/bin/env python3
"""
End-to-end commerce experiment for the EVM verifier.

Demonstrates the full PV-CVQC service loop with three distinct parties:

    client   compiles the circuit, garbles it into a TLP, registers the
             puzzle root on-chain and escrows a bounty (gas + margin)
    server   grinds the T sequential steps, builds a solver-bound claim
             and submits it; the bounty pays out in the same transaction
    attacker exercises the failure paths: front-running replay (reason 1),
             double claim (reason 5), lying output (reason 4)

and records a per-step ledger (balances, gas, events) to
bench/commerce_ledger.json, so the "server is in profit" claim is measured,
not asserted.

Usage (local anvil, no funds needed):
    uv run python python/experiment_commerce.py

Sweep mode (append profit rows over T x K):
    uv run python python/experiment_commerce.py --sweep-t 1,10,25,50,100 --k 8

Live (three funded cast keystores):
    uv run python python/experiment_commerce.py --rpc-url $ETH_SEPOLIA_RPC \
        --client-account client --server-account server --attacker-account spare
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(EVM_ROOT.parent.parent))
sys.path.insert(0, str(EVM_ROOT.parent.parent / "Quantum_vertification_artifact"))

from demo_eth import (  # noqa: E402
    ANVIL_ADDRESS,
    REASONS,
    REJECTED_TOPIC,
    VERIFIED_TOPIC,
    cast,
    run,
    send_timed,
    tx_hash,
    wait_for_node,
)
from gen_fixtures import build_claim, puzzle_root, serialize_claim  # noqa: E402
from timelock_puzzle.tlp_garbling import PythonGarbledTLP  # noqa: E402

# Anvil's well-known accounts — free ether, no real funds involved.
ANVIL_KEYS = {
    "client": "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "server": "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "attacker": "0x8b3a350cf5c3419adc7b20c10b5a3d458d15cc9ac3389a4d09be0b19a37a4519",
}

# Honest-claim gas fit from the Sepolia K sweep: gas = BASE + PER_CHECK * K.
EST_BASE_GAS = 65_210
EST_PER_CHECK_GAS = 29_826


def balance_of(addr: str, rpc: str) -> int:
    return int(run(["cast", "balance", addr, "--rpc-url", rpc], "balance"))


def receipt(tx: str, rpc: str) -> dict:
    return json.loads(run(["cast", "receipt", tx, "--rpc-url", rpc, "--json"], "receipt"))


def verdict_of(tx: str, rpc: str) -> tuple[str, int | None]:
    """('verified', s) or ('rejected', reason) from the receipt's logs."""
    for log in receipt(tx, rpc).get("logs", []):
        t0 = (log.get("topics") or [""])[0]
        data = bytes.fromhex(log.get("data", "0x").removeprefix("0x"))
        if t0 == VERIFIED_TOPIC:
            return "verified", data[-1]
        if t0 == REJECTED_TOPIC:
            return "rejected", data[-1] if data else 255
    return "no-event", None


def auth_for(name: str, args) -> list[str]:
    """cast auth flags for one role.

    A live account spec is either a cast keystore name (password taken from
    the KEYSTORE_PASSWORD env var, so the run is non-interactive) or a raw
    `0x` private key (useful for ephemeral funded roles).
    """
    if args.rpc_url is None:
        return ["--private-key", ANVIL_KEYS[name]]
    spec = args.accounts[name]
    if spec.startswith("0x"):
        return ["--private-key", spec]
    auth = ["--account", spec]
    if os.environ.get("KEYSTORE_PASSWORD"):
        auth += ["--password", os.environ["KEYSTORE_PASSWORD"]]
    return auth

def send(role: str, args, rpc: str, ledger: list, label: str, value: str | None, *call: str) -> dict:
    """One timed, balance-accounted `cast send` from a role's account."""
    addr = role_address(role, args)
    before = balance_of(addr, rpc)
    cmd = ["send", args.verifier, *call, *auth_for(role, args), "--rpc-url", rpc, "--json"]
    if value is not None:
        cmd += ["--value", value]
    h, ms = send_timed(cmd, label)
    rec = receipt(h, rpc)
    gas = int(rec.get("gasUsed", "0x0"), 16)
    price = int(rec.get("effectiveGasPrice", "0x0"), 16)
    row = {
        "step": label,
        "role": role,
        "tx": h,
        "gas_used": gas,
        "gas_price_wei": price,
        "gas_cost_wei": gas * price,
        "value_wei": int(value) if value else 0,
        "latency_ms": round(ms, 1),
        "balance_before_wei": before,
        "balance_after_wei": balance_of(addr, rpc),
        "address": addr,
    }
    kind, code = verdict_of(h, rpc)
    if kind != "no-event":
        row["verdict"], row["reason"] = kind, code
    ledger.append(row)
    tag = ""
    if row.get("verdict") == "rejected":
        tag = f"  -> REJECTED reason {row['reason']} ({REASONS.get(row['reason'], '?')})"
    elif row.get("verdict") == "verified":
        tag = "  -> VERIFIED"
    print(f"   {label}: gas {gas:,}{tag}")
    return row


def role_address(role: str, args) -> str:
    if args.rpc_url is None:
        out = run(["cast", "wallet", "address", "--private-key", ANVIL_KEYS[role]], "addr")
    else:
        spec = args.accounts[role]
        if spec.startswith("0x"):
            out = run(["cast", "wallet", "address", "--private-key", spec], "addr")
        else:
            cmd = ["cast", "wallet", "address", "--account", spec]
            if os.environ.get("KEYSTORE_PASSWORD"):
                cmd += ["--password", os.environ["KEYSTORE_PASSWORD"]]
            out = run(cmd, "addr")
    return out.splitlines()[-1].strip()


def deploy(rpc: str, admin: str, auth: list[str]) -> str:
    cmd = [
        "forge", "create", "src/QuantumVerifier.sol:QuantumVerifier",
        "--rpc-url", rpc, "--broadcast", *auth,
        "--constructor-args", admin, "0x0000000000000000000000000000000000000000", "0",
    ]
    out = run(cmd, "deploy")
    for line in out.splitlines():
        if line.startswith("Deployed to:"):
            return line.split()[-1]
    raise SystemExit(f"could not parse deploy output:\n{out[-1500:]}")


def make_puzzle(t: int):
    """Client-side: garble the demo circuit and seal it in a TLP (PGen only)."""
    tlp = PythonGarbledTLP(lam=128, message_size=128, T=t, use_sha256=False,
                           garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    return tlp, pp, Z


def price_bounty(k: int, gas_price_wei: int, margin_wei: int) -> int:
    """gas + margin: verification gas estimate plus the server's margin."""
    est_gas = EST_BASE_GAS + EST_PER_CHECK_GAS * k
    return est_gas * gas_price_wei + margin_wei


def server_margin(args, rpc: str, server_addr: str) -> tuple[int, str]:
    """The server's labor price in wei, plus where it came from.

    With --quote-from this is the server's own published quote
    (FeeQuoteRegistry.quoteOf); without it, the legacy client-side
    --margin-usd guess.
    """
    if args.quote_from:
        out = run(["cast", "call", args.quote_from, "quoteOf(address)(uint96)",
                   server_addr, "--rpc-url", rpc], "quoteOf")
        wei = int(out.strip().splitlines()[-1].split()[0], 0)
        if wei == 0:
            raise SystemExit(
                f"server {server_addr} has no quote in {args.quote_from} — "
                "have the server publish one (python/publish_quotes.py)")
        return wei, f"registry {args.quote_from}"
    return (int(args.margin_usd / args.eth_usd * 1e18) if args.eth_usd else 0,
            f"--margin-usd {args.margin_usd} (client guess)")


def register(client: str, args, rpc: str, ledger: list, root: bytes, bounty: int) -> int:
    zero32 = "0x" + "00" * 32
    row = send(
        "client", args, rpc, ledger, "registerPuzzle", str(bounty),
        "registerPuzzle(bytes32,bytes32,bytes32,uint32,uint96)",
        zero32, zero32, f"0x{root.hex()}", "0", str(bounty),
    )
    count = int(run(["cast", "call", args.verifier, "puzzleCount()",
                     "--rpc-url", rpc], "puzzleCount"), 16)
    print(f"   puzzle_id = {count}  root = 0x{root.hex()[:16]}...  bounty = {bounty / 1e18:.6f} ETH")
    del row
    return count


def run_cycle(args, rpc: str, ledger: list, addrs: dict, t: int, k: int) -> dict | None:
    """One full commercial loop: register -> solve -> verify -> payout."""
    verifier = args.verifier

    # ---- client: compute, garble, price, escrow ---------------------------
    t0 = time.perf_counter()
    tlp, pp, Z = make_puzzle(t)
    setup_ms = (time.perf_counter() - t0) * 1000

    server20 = bytes.fromhex(addrs["server"].removeprefix("0x").lower())
    root = puzzle_root(Z, solver=server20)          # client-side, no solving
    gas_price = int(run(["cast", "gas-price", "--rpc-url", rpc], "gas-price"))
    margin_wei, quote_src = server_margin(args, rpc, addrs["server"])
    bounty = price_bounty(k, gas_price, margin_wei)

    print(f"==> client: T={t} garble+seal {setup_ms:.0f}ms, bounty {bounty / 1e18:.6f} ETH "
          f"(gas est + {margin_wei / 1e18:.6f} ETH margin [{quote_src}] "
          f"@ {gas_price / 1e9:.2f} gwei)")
    pid = register("client", args, rpc, ledger, root, bounty)

    # ---- hand the puzzle to the server (in-process; would be a network msg)
    # ---- server: solve the time-lock, build the bound claim, submit --------
    t0 = time.perf_counter()
    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
    solve_ms = (time.perf_counter() - t0) * 1000
    non_reusable = sorted(witness["gate_keys"].keys())
    claim = build_claim(tlp, Z, witness, s, y, non_reusable[:k], solver=server20)
    assert claim["puzzle_hash"] == root, "server root != registered root"
    claim_hex = serialize_claim(claim).hex()
    print(f"==> server: solved in {solve_ms:.0f}ms, claim {len(claim_hex) // 2} B (K={k})")

    # Server acceptance is implicit but checked: the bounty must at least
    # cover the quoted margin. The gas leg is the client's reimbursement
    # estimate; residual gas-price drift between estimate and execution is
    # the server's only exposure. A server that finds the bounty too low
    # simply refuses (does no work) and the client reclaims.
    if bounty < margin_wei:
        raise SystemExit(f"server refuses: bounty {bounty} < quoted margin {margin_wei}")

    server_before = balance_of(addrs["server"], rpc)
    row = send("server", args, rpc, ledger, "verify_honest", None,
               "submitAndVerify(uint32,bytes)", str(pid), f"0x{claim_hex}")
    paid = row["balance_after_wei"] - server_before + row["gas_cost_wei"]
    # On OP-Stack L2s the sender's debit includes an L1 data-fee component that
    # `gas_used * effectiveGasPrice` does not capture, so the net payout is the
    # bounty minus that small residual — compare with a tolerance, not exactly.
    l1_fee_residual_wei = max(bounty - paid, 0)
    ok = row.get("verdict") == "verified" and l1_fee_residual_wei <= bounty // 50
    print(f"   bounty received: {paid / 1e18:.8f} ETH (expected {bounty / 1e18:.8f}) | "
          f"gas {row['gas_cost_wei']:,} wei | server net {paid - row['gas_cost_wei']:,} wei")

    return {
        "pid": pid, "bounty_wei": bounty, "claim_hex": claim_hex, "ok": ok,
        "margin_wei": margin_wei, "quote_src": quote_src,
        "l1_fee_residual_wei": l1_fee_residual_wei,
        "solve_ms": solve_ms, "setup_ms": setup_ms, "gas_used": row["gas_used"],
        "gas_cost_wei": row["gas_cost_wei"],
        "server_profit_wei": paid - row["gas_cost_wei"],
        "s": s, "y": y, "witness": witness, "non_reusable": non_reusable,
        "tlp": tlp, "Z": Z, "pp": pp,
    }


def run_controls(args, rpc: str, ledger: list, addrs: dict, main: dict) -> None:
    """Attack paths + client protections, on top of a completed honest cycle."""
    verifier = args.verifier
    server20 = bytes.fromhex(addrs["server"].removeprefix("0x").lower())
    attacker20 = bytes.fromhex(addrs["attacker"].removeprefix("0x").lower())

    # 1. Front-running replay: attacker resubmits the server's exact claim.
    print("==> control: front-run replay of the honest claim")
    row = send("attacker", args, rpc, ledger, "front_run_replay", None,
               "submitAndVerify(uint32,bytes)", str(main["pid"]), f"0x{main['claim_hex']}")
    assert row.get("reason") == 1, f"expected reason 1, got {row.get('reason')}"

    # 2. Double claim: server resubmits after being paid.
    print("==> control: double claim of a paid bounty")
    row = send("server", args, rpc, ledger, "double_claim", None,
               "submitAndVerify(uint32,bytes)", str(main["pid"]), f"0x{main['claim_hex']}")
    assert row.get("reason") == 5, f"expected reason 5, got {row.get('reason')}"

    # 3. Lying solver: second puzzle, attacker submits a flipped output bit.
    print("==> control: lying solver (flipped s_claim)")
    tlp, pp, Z = make_puzzle(args.t)
    attacker20_root = puzzle_root(Z, solver=attacker20)
    gas_price = int(run(["cast", "gas-price", "--rpc-url", rpc], "gas-price"))
    margin_wei, _ = server_margin(args, rpc, addrs["server"])
    bounty = price_bounty(args.k, gas_price, margin_wei)
    pid2 = register("client", args, rpc, ledger, attacker20_root, bounty)

    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
    non_reusable = sorted(witness["gate_keys"].keys())
    cheat = build_claim(tlp, Z, witness, s ^ 1, y, non_reusable[:args.k], solver=attacker20)
    cheat_hex = serialize_claim(cheat).hex()
    attacker_before = balance_of(addrs["attacker"], rpc)
    row = send("attacker", args, rpc, ledger, "lying_solve", None,
               "submitAndVerify(uint32,bytes)", str(pid2), f"0x{cheat_hex}")
    assert row.get("reason") == 4, f"expected reason 4, got {row.get('reason')}"
    delta = balance_of(addrs["attacker"], rpc) - attacker_before
    print(f"   attacker balance delta: {delta} wei (gas loss only)")

    # 4. The client reclaims the bounty nobody honestly claimed.
    print("==> control: reclaim of unclaimed bounty")
    client_before = balance_of(addrs["client"], rpc)
    row = send("client", args, rpc, ledger, "reclaim_unclaimed", None,
               "reclaimBounty(uint32)", str(pid2))
    got = row["balance_after_wei"] - client_before + row["gas_cost_wei"]
    assert got == bounty, f"reclaim returned {got}, expected {bounty}"
    print(f"   client recovered {got / 1e18:.6f} ETH")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--t", type=int, default=1)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--rpc-url", default=None)
    ap.add_argument("--port", type=int, default=8545)
    ap.add_argument("--verifier", default=None,
                    help="reuse a deployed verifier (must be the NEW bytecode "
                         "with registerPuzzle(circuitHash,pkCommitment,puzzleHash,fee,bounty))")
    ap.add_argument("--accounts", nargs=3, metavar=("CLIENT", "SERVER", "ATTACKER"),
                    default=["client", "server", "attacker"],
                    help="cast keystore names for the three roles (live mode)")
    ap.add_argument("--margin-usd", type=float, default=0.50,
                    help="server profit margin per verified claim, USD "
                         "(ignored when --quote-from is given)")
    ap.add_argument("--quote-from", default=None,
                    help="FeeQuoteRegistry address: read the server's quoted "
                         "margin from chain instead of --margin-usd")
    ap.add_argument("--eth-usd", type=float, default=3000.0)
    ap.add_argument("--sweep-t", default=None,
                    help="comma list of T values; runs the honest cycle per T "
                         "and appends profit rows to the ledger")
    ap.add_argument("--sweep-k", default=None)
    ap.add_argument("--skip-controls", action="store_true")
    args = ap.parse_args()

    live = args.rpc_url is not None
    rpc = args.rpc_url or f"http://localhost:{args.port}"
    if args.accounts and len(args.accounts) == 3:
        # keystore names arrive as a positional triple; index them by role
        args.accounts = dict(zip(("client", "server", "attacker"), args.accounts))
    anvil = None
    if not live:
        print("==> 1. Starting Anvil")
        anvil = subprocess.Popen(
            ["anvil", "--port", str(args.port), "--silent"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_for_node(rpc)
        args.accounts = None  # roles use the well-known dev keys
    else:
        print(f"==> 1. Live network: {rpc}")

    addrs = {role: role_address(role, args) for role in ("client", "server", "attacker")}
    for role, a in addrs.items():
        bal = balance_of(a, rpc)
        print(f"   {role:8s} {a}  {bal / 1e18:.6f} ETH")
    if not live:
        # The attacker dev key is not one of anvil's prefunded defaults; fund
        # it from the client so all three roles can pay gas.
        if balance_of(addrs["attacker"], rpc) < 1e18:
            run(["cast", "send", addrs["attacker"], "--value", "10ether",
                 "--private-key", ANVIL_KEYS["client"], "--rpc-url", rpc],
                "fund attacker")
            print(f"   funded attacker with 10 ETH (local chain)")
    for role, a in addrs.items():
        if balance_of(a, rpc) == 0:
            raise SystemExit(f"{role} has no funds — fund it first")
    if args.verifier is None:
        args.verifier = deploy(rpc, addrs["client"], auth_for("client", args))
        print(f"   deployed verifier {args.verifier} (admin = client, free mode)")

    ledger: list[dict] = []
    chain_id = run(["cast", "chain-id", "--rpc-url", rpc], "chain-id")
    summary: dict = {"venue": "anvil" if not live else f"sepolia-{chain_id}",
                     "chain_id": chain_id, "rpc": rpc, "verifier": args.verifier,
                     "addrs": addrs, "margin_usd": args.margin_usd,
                     "quote_registry": args.quote_from,
                     "eth_usd": args.eth_usd,
                     "params": {"T": args.t, "K": args.k},
                     "cycles": [], "steps": ledger}

    try:
        if args.sweep_t or args.sweep_k:
            ts = [int(x) for x in args.sweep_t.split(",")] if args.sweep_t else [args.t]
            ks = [int(x) for x in args.sweep_k.split(",")] if args.sweep_k else [args.k]
            for t in ts:
                for k in ks:
                    print(f"\n{'=' * 60}\n== cycle T={t} K={k}\n{'=' * 60}")
                    args.t, args.k = t, k
                    cyc = run_cycle(args, rpc, ledger, addrs, t, k)
                    assert cyc["ok"], "honest cycle did not pay out"
                    summary["cycles"].append(
                        {kk: cyc[kk] for kk in
                         ("pid", "bounty_wei", "solve_ms", "setup_ms",
                          "gas_used", "gas_cost_wei", "server_profit_wei")}
                        | {"T": t, "K": k}
                    )
        else:
            cyc = run_cycle(args, rpc, ledger, addrs, args.t, args.k)
            assert cyc["ok"], "honest cycle did not pay out"
            summary["cycles"].append(
                {kk: cyc[kk] for kk in
                 ("pid", "bounty_wei", "solve_ms", "setup_ms",
                  "gas_used", "gas_cost_wei", "server_profit_wei")}
                | {"T": args.t, "K": args.k}
            )
            if not args.skip_controls:
                run_controls(args, rpc, ledger, addrs, cyc)

        out = EVM_ROOT / "bench" / "commerce_ledger.json"
        out.parent.mkdir(exist_ok=True)
        sessions = json.loads(out.read_text()) if out.exists() else []
        sessions.append(summary)
        out.write_text(json.dumps(sessions, indent=2))
        print(f"\n==> ledger appended to {out}")
        for c in summary["cycles"]:
            profit_usd = c["server_profit_wei"] / 1e18 * args.eth_usd
            print(f"   T={c.get('T')} K={c.get('K')}  server profit "
                  f"{c['server_profit_wei'] / 1e18:.8f} ETH (~${profit_usd:.4f})  "
                  f"solve {c['solve_ms']:.0f}ms")
    finally:
        if anvil is not None:
            anvil.terminate()
            anvil.wait(timeout=5)


if __name__ == "__main__":
    main()
