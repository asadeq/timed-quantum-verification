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
    args = ap.parse_args()

    rpc = f"http://localhost:{args.port}"
    K = args.spot_checks

    # ---- 1. Off-chain TLP ------------------------------------------------
    print(f"==> 1. Generating TLP (off-chain, PRGC, lam={args.lam}, "
          f"msg={args.msg_bits}, T={args.T})")
    tlp = PythonGarbledTLP(lam=args.lam, message_size=args.msg_bits,
                           T=args.T, use_sha256=False, garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
    assert tlp.PVerify(s, y, Z), "honest PVerify failed"
    non_reusable = sorted(witness["gate_keys"].keys())
    print(f"   s = {s}, |y| = {len(y)} B, non-reusable gates = {len(non_reusable)}")

    honest = build_claim(tlp, Z, witness, s, y, non_reusable[:K])
    cheat = build_claim(tlp, Z, witness, s ^ 1, y, non_reusable[:K])
    puzzle_hash = honest["puzzle_hash"]
    claim_hex = serialize_claim(honest).hex()
    cheat_hex = serialize_claim(cheat).hex()
    print(f"   puzzle_hash = 0x{puzzle_hash.hex()}")
    print(f"   claim (K={K}) = {len(claim_hex) // 2} bytes")

    # ---- 2. Start Anvil ---------------------------------------------------
    print("==> 2. Starting Anvil (local chain, no real funds)")
    anvil = subprocess.Popen(
        ["anvil", "--port", str(args.port), "--silent"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_node(rpc)

        # ---- 3. Deploy ----------------------------------------------------
        print("==> 3. Deploying QuantumVerifier (free mode)")
        env = {
            **dict(__import__("os").environ),
            "PRIVATE_KEY": ANVIL_PK,
            "ADMIN_ADDRESS": ANVIL_ADDRESS,
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
        print("==> 4. registerPuzzle (admin)")
        zero32 = "0x" + "00" * 32
        cast([
            "send", verifier,
            "registerPuzzle(bytes32,bytes32,bytes32,uint32)",
            zero32, zero32, f"0x{puzzle_hash.hex()}", "0",
            "--private-key", ANVIL_PK, "--rpc-url", rpc, "--json",
        ], "registerPuzzle")
        print(f"   stored puzzle_hash = 0x{puzzle_hash.hex()} (puzzle_id = 1)")

        # ---- 5a. Honest claim ----------------------------------------------
        print(f"==> 5a. submitAndVerify — honest solver (K={K})")
        h = tx_hash(cast([
            "send", verifier,
            "submitAndVerify(uint32,bytes)",
            "1", f"0x{claim_hex}",
            "--private-key", ANVIL_PK, "--rpc-url", rpc, "--json",
        ], "submit honest"))
        print(f"   tx {h}")
        _print_verdict(h, rpc)

        # ---- 5b. Cheating claim --------------------------------------------
        print("==> 5b. submitAndVerify — lying solver (s_claim flipped)")
        h = tx_hash(cast([
            "send", verifier,
            "submitAndVerify(uint32,bytes)",
            "1", f"0x{cheat_hex}",
            "--private-key", ANVIL_PK, "--rpc-url", rpc, "--json",
        ], "submit cheat"))
        print(f"   tx {h}")
        _print_verdict(h, rpc)

        # ---- 5c. Unknown puzzle --------------------------------------------
        print("==> 5c. submitAndVerify — unknown puzzle id (999)")
        h = tx_hash(cast([
            "send", verifier,
            "submitAndVerify(uint32,bytes)",
            "999", f"0x{claim_hex}",
            "--private-key", ANVIL_PK, "--rpc-url", rpc, "--json",
        ], "submit unknown"))
        print(f"   tx {h}")
        _print_verdict(h, rpc)

        print()
        print("Done. An honest claim verifies; a flipped s_claim is rejected")
        print("with reason 4 (Goldreich-Levin); an unknown puzzle is rejected")
        print("with reason 0.")
    finally:
        anvil.terminate()
        anvil.wait(timeout=5)


if __name__ == "__main__":
    main()
