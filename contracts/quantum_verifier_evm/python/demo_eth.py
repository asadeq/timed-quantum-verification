#!/usr/bin/env python3
"""
End-to-end Quantum-Verification demo on a local Ethereum node (Anvil).

This is the EVM counterpart of `scripts/verify_sdk.py`. Flow:

  1. PSetup -> PGen -> PSolve off-chain (real TLP, PRGC mode).
  2. Merkle-ize the puzzle body off-chain (bitmap header, see
     docs/WIRE_FORMAT_EVM.md) -> puzzle_hash.
  3. Start Anvil, deploy QuantumVerifier (free mode).
  4. registerPuzzle — stores ONLY the root commitment on-chain.
  5. submitAndVerify (K spot checks):
       * honest claim        -> Verified event
       * s_claim flipped     -> Rejected event, reason 4 (Goldreich-Levin)
       * unknown puzzle id   -> Rejected event, reason 0

The ~49 KB puzzle body never touches the chain. The claim is ~6.9 KB for K=8.

Requires: foundryup (anvil + cast on PATH). No web3.py needed — this drives
`cast` over subprocess, so there are no new pip dependencies.

Usage:
    uv run python contracts/quantum_verifier_evm/python/demo_eth.py
    uv run python contracts/quantum_verifier_evm/python/demo_eth.py \
        --spot-checks 4 --T 2
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent

# Foundry (anvil/cast/forge) is installed under ~/.foundry/bin, which is not
# always on PATH. Prepend it so the demo works without a manual export.
_FOUNDRY_BIN = Path.home() / ".foundry" / "bin"
if _FOUNDRY_BIN.is_dir():
    os.environ["PATH"] = str(_FOUNDRY_BIN) + os.pathsep + os.environ.get("PATH", "")
for _tool in ("anvil", "cast", "forge"):
    if shutil.which(_tool) is None:
        raise SystemExit(
            f"`{_tool}` not found. Install Foundry first:\n"
            "  curl -L https://foundry.paradigm.xyz | bash && foundryup\n"
            "(or add ~/.foundry/bin to PATH)"
        )

sys.path.insert(0, str(EVM_ROOT / "python"))
sys.path.insert(0, str(EVM_ROOT.parent.parent))
sys.path.insert(0, str(EVM_ROOT.parent.parent / "Quantum_vertification_artifact"))

from gen_fixtures import (  # noqa: E402
    build_claim,
    flip_bit,
    serialize_claim,
)
from timelock_puzzle.tlp_garbling import PythonGarbledTLP  # noqa: E402

# Anvil's well-known account 0 — free ether, no real funds involved.
ANVIL_PK = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
ANVIL_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"


def run(cmd: list[str], label: str) -> str:
    """Run a command, print its label, return stripped stdout."""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"!! {label} failed:")
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])
        raise SystemExit(1)
    return proc.stdout.strip()


def cast(args: list[str], label: str) -> str:
    return run(["cast", *args], label)


def send_timed(args: list[str], label: str) -> tuple[str, float]:
    """`cast send` with wall-clock timing around submit → receipt."""
    start = time.perf_counter()
    out = cast(args, label)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return json.loads(out)["transactionHash"], elapsed_ms


def _bench_row(name: str, tx: str, latency_ms: float, rpc: str) -> dict:
    """Receipt-derived gas/fee/latency row for bench/evm_results.json."""
    rec = json.loads(run(["cast", "receipt", tx, "--rpc-url", rpc, "--json"], "receipt"))
    gas = int(rec.get("gasUsed", "0x0"), 16)
    eff = int(rec.get("effectiveGasPrice", "0x0"), 16)
    return {
        "name": name,
        "tx": tx,
        "block": int(rec.get("blockNumber", "0x0"), 16),
        "gas_used": gas,
        "effective_gas_price_wei": eff,
        "fee_wei": gas * eff,
        "latency_ms": round(latency_ms, 1),
    }


def tx_hash(send_stdout: str) -> str:
    """`cast send --json` returns a JSON object with the tx hash."""
    return json.loads(send_stdout)["transactionHash"]


def receipt_logs(tx: str, rpc: str) -> list[dict]:
    out = json.loads(run(
        ["cast", "receipt", tx, "--rpc-url", rpc, "--json"], "receipt"
    ))
    return [log for log in out.get("logs", []) if log]


# keccak selectors, matching the contract's events exactly.
VERIFIED_TOPIC = "0x1fabb2fa1c6487a789cedb257be372193547456bfe9302b917f5a2ceca60916f"
REJECTED_TOPIC = "0x53250a5d6caa2d5cbb589ba431118f4ecf190aed43bdad5852854f73425a65d4"
REASONS = {
    0: "puzzle not registered",
    1: "header Merkle path invalid",
    2: "gate Merkle path invalid",
    3: "Yao spot-check failed",
    4: "Goldreich-Levin check failed",
    5: "bounty already claimed",
}


def _print_verdict(tx: str, rpc: str) -> None:
    """Decode Verified/Rejected from the receipt's logs."""
    status = json.loads(run([
        "cast", "receipt", tx, "--rpc-url", rpc, "--json"], "receipt"
    ))
    verdict = None
    for log in status.get("logs", []):
        t0 = (log.get("topics") or [""])[0]
        data = bytes.fromhex(log.get("data", "0x").removeprefix("0x"))
        if t0 == VERIFIED_TOPIC:
            verdict = f"VERIFIED (s = {data[-1]})"
        elif t0 == REJECTED_TOPIC:
            reason = data[-1] if data else 255
            verdict = f"REJECTED (reason {reason} = {REASONS.get(reason, '?')})"
    print(f"   -> {verdict if verdict else 'no verifier event in logs'}")


def wait_for_node(rpc: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = subprocess.run(["cast", "chain-id", "--rpc-url", rpc],
                              capture_output=True, text=True)
        if proc.returncode == 0:
            return
        time.sleep(0.3)
    raise SystemExit("anvil did not come up")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--T", type=int, default=1)
    ap.add_argument("--lam", type=int, default=128)
    ap.add_argument("--msg-bits", type=int, default=128)
    ap.add_argument("--spot-checks", type=int, default=8)
    ap.add_argument("--port", type=int, default=8545)
    ap.add_argument("--venue-label", default=None,
                    help="short venue name recorded in results (e.g. anvil, "
                         "sepolia, base-sepolia). Default: 'anvil' locally, "
                         "otherwise 'chain-<id>'.")
    ap.add_argument("--repeat", type=int, default=1,
                    help="number of honest-claim submissions per puzzle "
                         "(for averaging gas; each is a real tx)")
    ap.add_argument("--solve-repeat", type=int, default=1,
                    help="off-chain PSolve repetitions for timing; the median "
                         "is recorded (min/max for error bars). Costs no gas.")
    ap.add_argument("--rpc-url", default=None,
                    help="target a live network (e.g. $BASE_SEPOLIA_RPC) "
                         "instead of starting a local Anvil")
    ap.add_argument("--private-key", default=None,
                    help="funded sender key for --rpc-url. NEVER use a "
                         "mainnet key; testnet-only wallets.")
    ap.add_argument("--account", default=None,
                    help="name of a local cast keystore (import once with "
                         "`cast wallet import NAME` — the key never appears "
                         "in shell history or .env). Preferred over "
                         "--private-key.")
    ap.add_argument("--verifier", default=None,
                    help="reuse an already-deployed verifier address instead "
                         "of deploying a new one (useful on live networks)")
    ap.add_argument("--benchmark", action="store_true",
                    help="record gas/latency per tx into bench/evm_results.json")
    ap.add_argument("--bounty", default="0",
                    help="wei escrowed by registerPuzzle and paid atomically "
                         "to the first honest solver. Claims are bound to the "
                         "submitting address, so the bounty cannot be "
                         "front-run. Default 0 (verify-only).")
    args = ap.parse_args()

    live = args.rpc_url is not None
    if live and not (args.private_key or args.account):
        raise SystemExit("--rpc-url requires --private-key or --account")
    pk = args.private_key or ANVIL_PK
    # Auth flags appended to every cast send. A keystore with
    # KEYSTORE_PASSWORD set in the environment runs non-interactively.
    keystore_pw = os.environ.get("KEYSTORE_PASSWORD")
    auth = ["--account", args.account] if args.account else ["--private-key", pk]
    if args.account and keystore_pw:
        auth += ["--password", keystore_pw]
    if args.account:
        addr_cmd = ["cast", "wallet", "address", "--account", args.account]
        if keystore_pw:
            addr_cmd += ["--password", keystore_pw]
        out = run(addr_cmd, "wallet address")
    else:
        out = run(["cast", "wallet", "address", "--private-key", pk], "wallet address")
    sender = None
    if live:
        sender = out.splitlines()[-1].strip()
    # The account that will sign submitAndVerify — the claim's header leaf is
    # bound to this address, so it must be known before the claim is built.
    solver_addr = sender or ANVIL_ADDRESS
    solver20 = bytes.fromhex(solver_addr.removeprefix("0x").lower())
    rpc = args.rpc_url or f"http://localhost:{args.port}"
    chain_id = "31337" if not live else None
    if live:
        chain_id = run(["cast", "chain-id", "--rpc-url", rpc], "chain-id")
    venue = args.venue_label or ("anvil" if not live else f"chain-{chain_id}")
    bench = {
        "venue": venue,
        "chain_id": chain_id,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "params": {"T": args.T, "lam": args.lam, "msg_bits": args.msg_bits,
                   "K": args.spot_checks, "repeat": args.repeat,
                   "bounty_wei": args.bounty, "solver": solver_addr},
        "runs": [],
    }

    K = args.spot_checks

    # ---- 0. Pre-flight on live networks -----------------------------------
    if live:
        bal = run(["cast", "balance", sender, "--rpc-url", rpc], "balance")
        print(f"==> 0. Pre-flight: chain {chain_id}, sender {sender}, "
              f"balance {int(bal) / 1e18:.6f} ETH")
        if int(bal) == 0:
            raise SystemExit("sender has no funds — faucet first")

    # ---- 1. Off-chain TLP ------------------------------------------------
    print(f"==> 1. Generating TLP (off-chain, PRGC, lam={args.lam}, "
          f"msg={args.msg_bits}, T={args.T})")
    offchain_ms = {}
    t0 = time.perf_counter()
    tlp = PythonGarbledTLP(lam=args.lam, message_size=args.msg_bits,
                           T=args.T, use_sha256=False, garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    offchain_ms["psetup_garble_ms"] = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    Z = tlp.PGen(1, pp)
    offchain_ms["pgen_ms"] = (time.perf_counter() - t0) * 1000

    # Single-shot ms-scale timing is dominated by interpreter noise; repeat
    # and take the median (min/max recorded for error bars).
    solves = []
    for _ in range(max(1, args.solve_repeat)):
        t0 = time.perf_counter()
        s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
        solves.append((time.perf_counter() - t0) * 1000)
    solves.sort()
    offchain_ms["psolve_ms"] = statistics.median(solves)
    offchain_ms["psolve_ms_min"] = solves[0]
    offchain_ms["psolve_ms_max"] = solves[-1]
    offchain_ms["psolve_ms_n"] = len(solves)

    assert tlp.PVerify(s, y, Z), "honest PVerify failed"
    t0 = time.perf_counter()
    non_reusable = sorted(witness["gate_keys"].keys())
    honest = build_claim(tlp, Z, witness, s, y, non_reusable[:K], solver=solver20)
    offchain_ms["claim_build_ms"] = (time.perf_counter() - t0) * 1000

    bench["offchain_ms"] = offchain_ms
    cheat = build_claim(tlp, Z, witness, s ^ 1, y, non_reusable[:K], solver=solver20)
    puzzle_hash = honest["puzzle_hash"]
    claim_hex = serialize_claim(honest).hex()
    cheat_hex = serialize_claim(cheat).hex()
    print(f"   s = {s}, |y| = {len(y)} B, non-reusable gates = {len(non_reusable)}")
    print(f"   off-chain: psetup {offchain_ms['psetup_garble_ms']:.0f}ms | "
          f"pgen {offchain_ms['pgen_ms']:.0f}ms | "
          f"psolve {offchain_ms['psolve_ms']:.0f}ms | "
          f"claim-build {offchain_ms['claim_build_ms']:.1f}ms")

    # ---- 2. Chain setup ---------------------------------------------------
    anvil = None
    if not live:
        print("==> 2. Starting Anvil (local chain, no real funds)")
        anvil = subprocess.Popen(
            ["anvil", "--port", str(args.port), "--silent"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_for_node(rpc)
    else:
        print(f"==> 2. Using live network: {rpc}")

    try:
        if args.verifier:
            verifier = args.verifier
            print(f"==> 3. Reusing deployed verifier {verifier}")
        else:
            # ---- 3. Deploy ------------------------------------------------
            print("==> 3. Deploying QuantumVerifier (free mode)")
            env = {
                **dict(__import__("os").environ),
                "PRIVATE_KEY": pk,
                "ADMIN_ADDRESS": sender or ANVIL_ADDRESS,
                "PAYMENT_TOKEN": "0x0000000000000000000000000000000000000000",
                "FEE_PER_VERIFY": "0",
            }
            proc = subprocess.run(
                ["forge", "script", "script/Deploy.s.sol",
                 "--rpc-url", rpc, "--broadcast", "--skip-simulation"],
                capture_output=True, text=True, env=env, cwd=str(EVM_ROOT),
            )
            if proc.returncode != 0:
                print(proc.stdout[-2000:]); print(proc.stderr[-2000:])
                raise SystemExit(1)
            deploy_out = proc.stdout
            import re
            m = re.search(r"deployed at (0x[0-9a-fA-F]{40})", deploy_out)
            if not m:
                print(deploy_out[-2000:])
                raise SystemExit("could not parse deployed address")
            verifier = m.group(1)
        print(f"   verifier = {verifier}")

        # ---- 4. Register --------------------------------------------------
        print("==> 4. registerPuzzle (admin)"
              + (f", escrowing {int(args.bounty) / 1e18:.6f} ETH bounty"
                 if int(args.bounty) else ""))
        zero32 = "0x" + "00" * 32
        reg_cmd = [
            "send", verifier,
            "registerPuzzle(bytes32,bytes32,bytes32,uint32,uint96)",
            zero32, zero32, f"0x{puzzle_hash.hex()}", "0", args.bounty,
            *auth, "--rpc-url", rpc, "--json",
        ]
        if int(args.bounty):
            reg_cmd += ["--value", args.bounty]
        h, ms = send_timed(reg_cmd, "registerPuzzle")
        bench["runs"].append(_bench_row("registerPuzzle", h, ms, rpc))
        print(f"   tx {h}")
        # The registry assigns ids sequentially; on a reused verifier the new
        # puzzle is NOT id 1 — read the count back instead of assuming.
        count_raw = run(["cast", "call", verifier, "puzzleCount()",
                         "--rpc-url", rpc], "puzzleCount")
        puzzle_id = int(count_raw, 16)
        print(f"   stored puzzle_hash = 0x{puzzle_hash.hex()} (puzzle_id = {puzzle_id})")

        # ---- 5a. Honest claims (--repeat times, for gas averaging) ---------
        for rep in range(args.repeat):
            label = f"verify_honest_K{K}" if args.repeat == 1 else f"verify_honest_K{K}_r{rep}"
            tag = "" if args.repeat == 1 else f" [{rep + 1}/{args.repeat}]"
            print(f"==> 5a. submitAndVerify — honest solver (K={K}){tag}")
            h, ms = send_timed([
                "send", verifier,
                "submitAndVerify(uint32,bytes)",
                str(puzzle_id), f"0x{claim_hex}",
                *auth, "--rpc-url", rpc, "--json",
            ], f"submit honest {rep}")
            print(f"   tx {h}   ({ms/1000:.1f}s to receipt)")
            bench["runs"].append(_bench_row(label, h, ms, rpc))
            _print_verdict(h, rpc)

        # ---- 5b. Cheating claim --------------------------------------------
        print("==> 5b. submitAndVerify — lying solver (s_claim flipped)")
        h, ms = send_timed([
            "send", verifier,
            "submitAndVerify(uint32,bytes)",
            str(puzzle_id), f"0x{cheat_hex}",
            *auth, "--rpc-url", rpc, "--json",
        ], "submit cheat")
        print(f"   tx {h}   ({ms/1000:.1f}s to receipt)")
        bench["runs"].append(_bench_row("verify_cheat", h, ms, rpc))
        _print_verdict(h, rpc)

        # ---- 5c. Unknown puzzle --------------------------------------------
        print("==> 5c. submitAndVerify — unknown puzzle id (999)")
        h, ms = send_timed([
            "send", verifier,
            "submitAndVerify(uint32,bytes)",
            "999", f"0x{claim_hex}",
            *auth, "--rpc-url", rpc, "--json",
        ], "submit unknown")
        print(f"   tx {h}   ({ms/1000:.1f}s to receipt)")
        bench["runs"].append(_bench_row("verify_unknown_puzzle", h, ms, rpc))
        _print_verdict(h, rpc)

        if args.benchmark:
            out = EVM_ROOT / "bench" / "evm_results.json"
            out.parent.mkdir(exist_ok=True)
            existing = json.loads(out.read_text()) if out.exists() else []
            existing.append(bench)
            out.write_text(json.dumps(existing, indent=2))
            print(f"\nBenchmark rows appended to {out}")
    finally:
        if anvil is not None:
            anvil.terminate()
            anvil.wait(timeout=5)


if __name__ == "__main__":
    main()
