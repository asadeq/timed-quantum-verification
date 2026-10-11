#!/usr/bin/env python3
"""
End-to-end Quantum-Verification demo on Stellar Testnet.

Uses stellar-sdk's `ContractClient` directly — no `stellar contract invoke`
CLI, no JSON argument encoding. This matters because the CLI's JSON parser
corrupts BytesN values containing bytes >= 0x80 (UTF-8 mangling); building
SCVals here from raw bytes is exact.

Flow:
  1. PSetup + PGen + PSolve off-chain (real TLP, PRGC mode).
  2. Merkle-ize the puzzle body off-chain: header leaf + per-gate leaves
     bound up a SHA-256 tree to a root (puzzle_hash).
  3. register_puzzle — stores ONLY the root commitment on-chain.
  4. submit_and_verify — the claim carries Merkle proofs binding the
     header and each spot-checked gate back to the root, plus the Yao
     keys for the spot-check math and y_bits for the Goldreich-Levin check.

The 49 KB puzzle body never touches the chain. The claim is ~4 KB (K=1)
to ~28 KB (K=8).

Usage:
  uv run python scripts/verify_sdk.py [--contract <C...>] [--spot-checks K]
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Quantum_vertification_artifact"))

from stellar_sdk import Keypair, Network, scval  # noqa: E402
from stellar_sdk.base_soroban_server import ResourceLeeway  # noqa: E402
from stellar_sdk.contract import ContractClient  # noqa: E402
from stellar_sdk.xdr import ContractEvent  # noqa: E402

from timelock_puzzle.tlp_garbling import PythonGarbledTLP  # noqa: E402
from scripts.serialize import (  # noqa: E402
    build_circuit_spec,
    build_puzzle_meta,
    build_claim,
    puzzle_hash_from_claim,
)

RPC_URL = "https://soroban-testnet.stellar.org"
PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
IDENTITY_FILE = Path.home() / ".config" / "stellar" / "identity" / "alice.toml"

# Latest contract built from the current wasm (pad fix included) and
# inited with alice as admin, fee_per_verify = 0 (free mode).
# Re-deploy with ./scripts/deploy.sh if this one is stale or expired.
DEFAULT_CONTRACT = "CCIQ752ALQCXVT5XOEKDF5VKGCARBAN5VGXE25OFMUM7IK36QUXR3PUY"


def load_admin() -> Keypair:
    """Derive the admin keypair from the stellar CLI identity file."""
    text = IDENTITY_FILE.read_text()
    phrase = text.split('"')[1]
    return Keypair.from_mnemonic_phrase(phrase, index=0)


# ---------------------------------------------------------------------------
# Claim dict -> SCVal (must mirror the Rust #[contracttype] layout:
# structs -> SCMap keyed by field-name Symbols, tuples -> SCVec in order)
# ---------------------------------------------------------------------------

def path_scval(path) -> "SCVal":
    """Vec<(BytesN<32>, bool)> -> SCVec of 2-element SCVecs."""
    return scval.to_vec([
        scval.to_vec([scval.to_bytes(sib), scval.to_bool(bool(is_left))])
        for sib, is_left in path
    ])


def spot_check_scval(sc: dict) -> "SCVal":
    flat = [
        sc["table"][0][0], sc["table"][0][1],
        sc["table"][1][0], sc["table"][1][1],
    ]
    return scval.to_struct({
        "gate_index": scval.to_uint32(sc["gate_index"]),
        "k_l": scval.to_bytes(sc["k_l"]),
        "k_r": scval.to_bytes(sc["k_r"]),
        "k_o": scval.to_bytes(sc["k_o"]),
        "table": scval.to_vec([scval.to_bytes(ct) for ct in flat]),
        "merkle_path": path_scval(sc["merkle_path"]),
    })


def claim_scval(claim: dict) -> "SCVal":
    return scval.to_struct({
        "header": scval.to_struct({
            "r": scval.to_bytes(claim["r"]),
            "r_dot_m_xor_s": scval.to_uint32(claim["r_dot_m_xor_s"]),
            "non_reusable": scval.to_vec(
                [scval.to_uint32(gi) for gi in claim["non_reusable"]]
            ),
            "merkle_path": path_scval(claim["header_merkle_path"]),
        }),
        "spot_checks": scval.to_vec(
            [spot_check_scval(sc) for sc in claim["spot_checks"]]
        ),
        "y_bits": scval.to_vec([scval.to_uint32(b) for b in claim["y_bits"]]),
        "s_claim": scval.to_uint32(claim["s_claim"]),
    })


def spec_scval(spec: dict) -> "SCVal":
    return scval.to_struct({
        "lam": scval.to_uint32(spec["lam"]),
        "msg_bits": scval.to_uint32(spec["msg_bits"]),
        "t": scval.to_uint32(spec["T"]),
        "sha256_circuit": scval.to_uint32(spec["sha256_circuit"]),
    })


def invoke(client: ContractClient, fn: str, params: list, signer: Keypair):
    """Build, simulate, sign, submit, and return (native result, tx)."""
    tx = client.invoke(
        fn,
        parameters=params,
        source=signer.public_key,
        signer=signer,
        base_fee=1_000_000,
        addl_resources=ResourceLeeway(cpu_instructions=30_000_000),
        parse_result_xdr_fn=scval.to_native,
    )
    result = tx.sign_and_submit(signer)
    return result, tx


def print_events(client: ContractClient, tx) -> None:
    """Print the contract events emitted by the submitted transaction."""
    resp = tx.get_transaction_response
    if resp is None:
        resp = client.server.get_transaction(tx.send_transaction_response.hash)
    if resp.events is None or not resp.events.contract_events_xdr:
        return
    for group in resp.events.contract_events_xdr:
        for b64 in group:
            try:
                ce = ContractEvent.from_xdr(b64)
                v0 = ce.body.v0
                def topic_str(t):
                    if t.sym is not None:
                        return t.sym.sym.decode()
                    if t.vec is not None:
                        return tuple(e.sym.sym.decode() for e in t.vec.sc_vec)
                    return t.to_xdr()

                def scval_str(v):
                    if v.u32 is not None:
                        return v.u32.uint32
                    if v.address is not None:
                        from stellar_sdk import StrKey
                        acct = v.address.account_id.account_id
                        return StrKey.encode_ed25519_public_key(acct.ed25519.uint256)
                    if v.vec is not None:
                        return [scval_str(e) for e in v.vec.sc_vec]
                    if v.bool_ is not None:
                        return v.bool_
                    return v.to_xdr()

                topics = [topic_str(t) for t in v0.topics]
                print(f"   event {topics} data = {scval_str(v0.data)}")
            except Exception as ex:
                print(f"   event undecodable: {ex}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", default=DEFAULT_CONTRACT)
    ap.add_argument("--identity", default="alice")
    ap.add_argument("--T", type=int, default=1)
    ap.add_argument("--lam", type=int, default=128)
    ap.add_argument("--msg_bits", type=int, default=128)
    ap.add_argument("--fee", type=int, default=0)
    ap.add_argument("--spot-checks", type=int, default=1)
    ap.add_argument("--cheat", action="store_true",
                    help="flip s_claim — the claim must be rejected")
    args = ap.parse_args()

    admin = load_admin()
    print(f"admin = {admin.public_key}")
    client = ContractClient(args.contract, RPC_URL, PASSPHRASE)

    # ---- 1. Off-chain TLP ------------------------------------------------
    print("==> 1. Generating TLP (off-chain)")
    tlp = PythonGarbledTLP(lam=args.lam, message_size=args.msg_bits,
                           T=args.T, use_sha256=False, garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
    assert tlp.PVerify(s, y, Z), "honest PVerify failed"
    print(f"   s = {s}")

    spec = build_circuit_spec(tlp)
    meta = build_puzzle_meta(tlp, fee=args.fee)
    claim = build_claim(tlp, Z, witness, s, y,
                        spot_check_indices=list(
                            sorted(witness["gate_keys"].keys()))[: args.spot_checks]
                        )
    puzzle_hash = puzzle_hash_from_claim(claim)
    print(f"   puzzle_hash = {puzzle_hash.hex()}")
    print(f"   claim: {len(claim['spot_checks'])} spot check(s), "
          f"{len(claim['y_bits'])} y_bits, "
          f"{len(claim['header_merkle_path'])}-deep Merkle tree")

    # ---- 2. Register the commitment --------------------------------------
    print("==> 2. register_puzzle (on-chain commitment only)")
    puzzle_id, _ = invoke(
        client, "register_puzzle",
        [
            spec_scval(spec),
            scval.to_bytes(meta["circuit_hash"]),
            scval.to_bytes(meta["pk_commitment"]),
            scval.to_bytes(puzzle_hash),
            scval.to_uint32(meta["fee"]),
        ],
        admin,
    )
    print(f"   puzzle_id = {puzzle_id}")

    # ---- 3. Submit the claim ---------------------------------------------
    print("==> 3. submit_and_verify")
    if args.cheat:
        claim["s_claim"] = 1 - claim["s_claim"]
        print("   (lying: flipped s_claim)")
    caller = scval.to_address(admin.public_key)
    result, tx = invoke(
        client, "submit_and_verify",
        [caller, scval.to_uint32(int(puzzle_id)), claim_scval(claim)],
        admin,
    )
    print(f"   submit_and_verify -> {result}")
    print_events(client, tx)

    if result is True:
        print("\nVERIFIED: the on-chain contract accepted the quantum claim.")
    else:
        print("\nREJECTED: see the contract's 'rejected' event for the reason.")
        sys.exit(1)


if __name__ == "__main__":
    main()
