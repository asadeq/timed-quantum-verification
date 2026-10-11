#!/usr/bin/env python3
"""
Serialize a PythonGarbledTLP puzzle + witness into the structures used by
the on-chain Soroban verifier.

This is the single source of truth for both the Python side and the
Rust side. Any change here must be mirrored in `contracts/quantum_verifier/
src/types.rs` (and vice versa) and in `SPEC.md`.

Key point: the 49 KB puzzle body is **off-chain only**. It is Merkle-ized
here (`build_puzzle_merkle_tree`) into a root that `register_puzzle`
stores on-chain; the `Claim` submitted by `submit_and_verify` carries
Merkle proofs binding the header and the spot-checked gate tables back
to that root. See SPEC.md for the full wire format.

Usage (end-to-end example):

    from timelock_puzzle.tlp_garbling import PythonGarbledTLP
    from scripts.serialize import (
        build_circuit_spec, build_puzzle_meta, build_puzzle_from_z,
        build_claim, puzzle_hash_from_claim,
    )

    tlp = PythonGarbledTLP(lam=128, message_size=128, T=2,
                           use_sha256=False, garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)

    spec = build_circuit_spec(tlp)
    meta = build_puzzle_meta(tlp, fee=100)
    puzzle = build_puzzle_from_z(tlp, Z, pp)
    claim = build_claim(tlp, Z, witness, s, y)   # includes Merkle proofs
    puzzle_hash = puzzle_hash_from_claim(claim)  # what register_puzzle stores
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path
from typing import List, Tuple

# Make the artifact package importable when this script is run from
# anywhere inside the quantum_verification repo.
_ARTIFACT = Path(__file__).resolve().parent.parent / "Quantum_vertification_artifact"
if str(_ARTIFACT) not in sys.path:
    sys.path.insert(0, str(_ARTIFACT))

# 128-bit Yao per-wire key length, matching yao_helpers.KEY_LEN.
KEY_LEN = 16


def _be32(n: int) -> bytes:
    """Encode a non-negative int as big-endian u32."""
    if n < 0 or n > 0xFFFFFFFF:
        raise ValueError(f"out of u32 range: {n}")
    return struct.pack(">I", n)


def _be8(b: int) -> bytes:
    """Encode a single byte (0-255)."""
    if b < 0 or b > 0xFF:
        raise ValueError(f"out of u8 range: {b}")
    return bytes([b])


def _bytes_of_len(data: bytes, expected: int) -> bytes:
    """Pad or truncate `data` to exactly `expected` bytes."""
    if len(data) == expected:
        return data
    if len(data) < expected:
        return data.ljust(expected, b"\x00")
    return data[:expected]


def _pack_list(items: List[bytes]) -> bytes:
    """Prefix a list of byte-strings with its length (u32 BE)."""
    out = _be32(len(items))
    for item in items:
        out += item
    return out


# ---------------------------------------------------------------------------
# CircuitSpec
# ---------------------------------------------------------------------------

def build_circuit_spec(tlp) -> dict:
    """Build the immutable circuit spec for a TLP instance.

    This is fixed at PSetup time and can be hashed / committed to once.
    """
    return {
        "lam": tlp.lam,
        "msg_bits": tlp.message_size,
        "T": tlp.T,
        "sha256_circuit": 1 if tlp.use_sha256 else 0,
    }


def serialize_circuit_spec(spec: dict) -> bytes:
    """Serialize CircuitSpec to canonical bytes."""
    out = _be32(spec["lam"])
    out += _be32(spec["msg_bits"])
    out += _be32(spec["T"])
    out += _be8(spec["sha256_circuit"])
    return out


def circuit_spec_hash(spec: dict) -> bytes:
    """SHA-256 of the serialized spec — what the contract stores."""
    return hashlib.sha256(serialize_circuit_spec(spec)).digest()


# ---------------------------------------------------------------------------
# PuzzleMeta
# ---------------------------------------------------------------------------

def build_puzzle_meta(tlp, fee: int) -> dict:
    """Build the public per-puzzle metadata.

    The contract stores `circuit_hash` (which puzzle circuit) and
    `pk_commitment` (which garbling setup) plus a per-call fee.
    """
    C_tilde, pk = tlp.pp
    # For CRGC mode, pk['base_flipped'] is the secret; hash it.
    # For PRGC mode, pk holds wire_flip and the partition.
    # Either way, a hash of the pk dict is a sufficient commitment.
    pk_bytes = repr(pk).encode("utf-8")
    return {
        "circuit_hash": circuit_spec_hash(build_circuit_spec(tlp)),
        "pk_commitment": hashlib.sha256(pk_bytes).digest(),
        "fee": fee,
    }


def serialize_puzzle_meta(meta: dict) -> bytes:
    out = _bytes_of_len(meta["circuit_hash"], 32)
    out += _bytes_of_len(meta["pk_commitment"], 32)
    out += _be32(meta["fee"])
    return out


# ---------------------------------------------------------------------------
# Puzzle
# ---------------------------------------------------------------------------

def build_puzzle(tlp, pp) -> dict:
    """Build the per-instance puzzle structure.

    This is what the solver generates off-chain and the contract needs to
    spot-check against. It excludes encoded_inputA / encoded_inputB —
    those are only needed to *run* the circuit, not to verify a claim.
    """
    C_tilde, pk = pp
    if pk.get("mode") != "prgc":
        raise ValueError("build_puzzle requires PRGC mode")

    non_reusable = sorted(pk["non_reusable_gates"])
    # The tables and sealed boundary come from the LAST PGen call.
    # We can't reconstruct them from pp alone, so this function takes
    # them as part of the puzzle Z tuple. See build_puzzle_from_z().
    raise NotImplementedError(
        "use build_puzzle_from_z(tlp, Z, pp) — the yao_material lives "
        "inside the puzzle Z, not in pp"
    )


def build_puzzle_from_z(tlp, Z: tuple, pp) -> dict:
    """Build the Puzzle structure from a PGen output Z.

    Args:
        tlp: PythonGarbledTLP instance (PRGC mode).
        Z:   output of tlp.PGen(s, pp), i.e. (x_tilde, r, r_dot_m_xor_s).
        pp:  output of tlp.PSetup_Garble(), i.e. (C_tilde, pk).
    """
    C_tilde, pk = pp
    if pk.get("mode") != "prgc":
        raise ValueError("build_puzzle_from_z requires PRGC mode")

    x_tilde, r, r_dot_m_xor_s = Z
    encoded_inputA, encoded_inputB, yao_material = x_tilde

    non_reusable = sorted(yao_material["non_reusable"])
    # Serialize tables in sorted non-reusable-gate order.
    tables = [yao_material["tables"][gi] for gi in non_reusable]
    # Serialize sealed_boundary as (wire_id, ciphertext) pairs, sorted by wire.
    sealed_boundary = sorted(yao_material["boundary"].items())
    # Serialize out_perm as (wire_id, perm) pairs, sorted by wire.
    out_perm = sorted(yao_material["out_perm"].items())

    # We don't have m from the puzzle; it's not part of the public
    # commitment. The contract uses only r, r_dot_m_xor_s, and the claim.
    # (For Goldreich-Levin, m is a *secret* — only its inner product with
    # r is committed.)

    return {
        "r": r,
        "r_dot_m_xor_s": r_dot_m_xor_s,
        "non_reusable": non_reusable,
        "tables": tables,
        "sealed_boundary": sealed_boundary,
        "out_perm": out_perm,
    }


def serialize_puzzle(puzzle: dict) -> bytes:
    """Serialize Puzzle to canonical bytes."""
    out = _be32(len(puzzle["r"]))
    out += puzzle["r"]
    out += _be8(puzzle["r_dot_m_xor_s"])

    # non_reusable
    out += _pack_list([_be32(gi) for gi in puzzle["non_reusable"]])

    # tables — flatten the 2x2 per gate into 4 keys of 16 bytes each.
    flat_tables: List[bytes] = []
    for rows in puzzle["tables"]:
        for row in rows:              # row = [ct_for_00, ct_for_01]
            for ct in row:
                flat_tables.append(_bytes_of_len(ct, KEY_LEN))
    out += _pack_list(flat_tables)

    # sealed_boundary
    sealed_items: List[bytes] = []
    for wire_id, ct in puzzle["sealed_boundary"]:
        sealed_items.append(_be32(wire_id) + _bytes_of_len(ct, KEY_LEN))
    out += _pack_list(sealed_items)

    # out_perm
    perm_items: List[bytes] = []
    for wire_id, perm_bit in puzzle["out_perm"]:
        perm_items.append(_be32(wire_id) + _be8(perm_bit))
    out += _pack_list(perm_items)

    return out


def puzzle_hash(puzzle: dict) -> bytes:
    """SHA-256 of the serialized puzzle — what the contract commits to."""
    return hashlib.sha256(serialize_puzzle(puzzle)).digest()


# ---------------------------------------------------------------------------
# Puzzle Merkle tree + Claim
#
# The puzzle body is Merkle-ized off-chain. The tree has two kinds of leaves:
#
#   1. Header leaf   = SHA-256(r || r_dot_m_xor_s_be32 || non_reusable_be32...)
#   2. Gate leaf(gi) = SHA-256(tables[gi] || gi_be32)
#                       where tables[gi] is the 4-row-major ciphertexts (64 bytes)
#
# The Merkle root (puzzle_hash) is what's registered on-chain. Each Claim
# carries a Merkle path from the relevant leaf up to puzzle_hash, plus
# the actual gate tables/keys needed for the spot-check math.
# ---------------------------------------------------------------------------


def _gate_table_bytes(table_rows: List[List[bytes]]) -> bytes:
    """Concatenate the 4 ciphertexts of a gate's garbled truth table.

    `table_rows` is [[ct_00, ct_01], [ct_10, ct_11]]; we flatten row-major.
    """
    out = b""
    for row in table_rows:
        for ct in row:
            out += _bytes_of_len(ct, KEY_LEN)
    return out


def _merkle_leaf_gate(gi: int, table_rows: List[List[bytes]]) -> bytes:
    preimage = _gate_table_bytes(table_rows) + _be32(gi)
    return hashlib.sha256(preimage).digest()


def _merkle_leaf_header(r: bytes, r_dot_m_xor_s: int, non_reusable: List[int]) -> bytes:
    preimage = r + _be32(r_dot_m_xor_s)
    for gi in non_reusable:
        preimage += _be32(gi)
    return hashlib.sha256(preimage).digest()


def build_puzzle_merkle_tree(puzzle: dict) -> dict:
    """Build a Merkle tree over the puzzle body, off-chain.

    Returns:
        {
            "root": bytes(32),       # = puzzle_hash
            "gate_leaves": [(gi, leaf_hash, merkle_path_to_root)],
            "header_leaf": leaf_hash,
            "header_path": merkle_path_to_root,
        }
    """
    leaves: List[Tuple[str, bytes]] = []
    # Header leaf first.
    header_leaf = _merkle_leaf_header(
        puzzle["r"], puzzle["r_dot_m_xor_s"], puzzle["non_reusable"]
    )
    leaves.append(("header", header_leaf))
    # One leaf per gate.
    non_reusable = puzzle["non_reusable"]
    gate_leaves = []
    for idx, gi in enumerate(non_reusable):
        leaf = _merkle_leaf_gate(gi, puzzle["tables"][idx])
        leaves.append((f"gate_{gi}", leaf))
        gate_leaves.append((gi, leaf))

    # Build a binary tree bottom-up. Pad with copies of the last leaf if
    # the leaf count isn't a power of 2.
    level = [leaf for (_, leaf) in leaves]
    # Map name → leaf for path lookup.
    name_to_leaf = {name: leaf for (name, leaf) in leaves}
    # Map leaf_hash → name (for matching during path construction).
    leaf_to_name = {leaf: name for (name, leaf) in leaves}

    # Compute root.
    while len(level) > 1:
        next_level = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            next_level.append(hashlib.sha256(left + right).digest())
        level = next_level
    root = level[0]

    # For each leaf, build a path from leaf up to root. The contract's
    # verify_merkle uses:
    #   is_left=true  → preimage = sibling || current
    #   is_left=false → preimage = current || sibling
    # So "is_left=true" means the sibling is on the LEFT of me.
    # If I'm at position i and my sibling is at i+1 (right), I am the LEFT
    # child → is_left=false.
    # If I'm at position i+1 and my sibling is at i (left), I am the RIGHT
    # child → is_left=true.
    def path_for_v2(target_leaf):
        cur_level = [leaf for (_, leaf) in leaves]
        path = []
        while len(cur_level) > 1:
            next_level = []
            found_idx = -1
            for i in range(0, len(cur_level), 2):
                left = cur_level[i]
                right = cur_level[i + 1] if i + 1 < len(cur_level) else left
                combined = hashlib.sha256(left + right).digest()
                next_level.append(combined)
                if found_idx < 0 and (target_leaf == left or target_leaf == right):
                    if target_leaf == left:
                        path.append((right, False))  # left child: sibling on right
                    elif i + 1 < len(cur_level):
                        path.append((left, True))    # right child: sibling on left
                    else:
                        # Padded duplicate of left; treat as left-up.
                        path.append((left, False))
                    target_leaf = combined
                    found_idx = i // 2
            cur_level = next_level
        return path

    header_path = path_for_v2(header_leaf)
    gate_paths = {gi: path_for_v2(leaf) for gi, leaf in gate_leaves}

    return {
        "root": root,
        "header_leaf": header_leaf,
        "header_path": header_path,
        "gate_leaves": {gi: leaf for gi, leaf in gate_leaves},
        "gate_paths": gate_paths,
    }


def build_claim(
    tlp,
    Z: tuple,
    witness: dict,
    s_claim: int,
    y: bytes,
    spot_check_indices: List[int] | None = None,
) -> dict:
    """Build the per-call Claim from a PSolve witness.

    Returns a dict with the canonical Claim fields. Requires the puzzle
    dict too so we can build the Merkle tree; pass it via the witness.
    """
    if witness is None:
        raise ValueError("witness is None — call PSolve with return_witness=True")

    if spot_check_indices is None:
        # Default K=1 spot check. SPEC.md suggests K=8 for security, but
        # K=1 is enough for a Testnet demo and keeps the claim under the
        # per-tx CPU budget. The first non-reusable gate is picked.
        all_nr = sorted(witness["gate_keys"].keys())
        spot_check_indices = all_nr[:1]

    x_tilde, r, r_dot_m_xor_s = Z
    encoded_inputA, encoded_inputB, yao_material = x_tilde
    non_reusable = sorted(yao_material["non_reusable"])

    # Reconstruct the puzzle (off-chain) so we can Merkle-ize it.
    puzzle = {
        "r": r,
        "r_dot_m_xor_s": r_dot_m_xor_s,
        "non_reusable": non_reusable,
        "tables": [yao_material["tables"][gi] for gi in non_reusable],
        "sealed_boundary": sorted(yao_material["boundary"].items()),
        "out_perm": sorted(yao_material["out_perm"].items()),
    }
    tree = build_puzzle_merkle_tree(puzzle)

    spot_checks = []
    for gi in spot_check_indices:
        k_l, k_r, k_o = witness["gate_keys"][gi]
        idx = non_reusable.index(gi)
        table_rows = yao_material["tables"][gi]
        spot_checks.append({
            "gate_index": gi,
            "k_l": k_l,
            "k_r": k_r,
            "k_o": k_o,
            "table": table_rows,
            "merkle_path": tree["gate_paths"][gi],
        })

    # y_bits: pack the circuit-output bytes LSB-first.
    y_bits = []
    for byte in y:
        for i in range(8):
            y_bits.append((byte >> i) & 1)

    return {
        "r": r,
        "r_dot_m_xor_s": r_dot_m_xor_s,
        "non_reusable": non_reusable,
        "header_merkle_path": tree["header_path"],
        "spot_checks": spot_checks,
        "y_bits": y_bits,
        "s_claim": s_claim,
        "_puzzle_hash": tree["root"],
    }


def puzzle_hash_from_claim(claim: dict) -> bytes:
    """Return the puzzle_hash the contract will use, derived from a Claim."""
    return claim["_puzzle_hash"]


def serialize_claim(claim: dict) -> bytes:
    """Serialize Claim to canonical bytes.

    Layout (matches Rust `Claim` / `ClaimHeader` / `SpotCheckProof`):

      u32                       r_len
      Bytes                     r
      u32                       r_dot_m_xor_s
      u32                       non_reusable_len
      u32[]                     non_reusable
      u32                       header_merkle_path_len
      (BytesN<32>, u8)[]        header_merkle_path   (sibling, is_left)

      u32                       spot_checks_len
      SpotCheckProof[]:
        u32                       gate_index
        BytesN<16>                k_l
        BytesN<16>                k_r
        BytesN<16>                k_o
        BytesN<16>                table.0  (ct for (a,b)=(0,0))
        BytesN<16>                table.1
        BytesN<16>                table.2
        BytesN<16>                table.3
        u32                       merkle_path_len
        (BytesN<32>, u8)[]        merkle_path

      u32                       y_bits_len
      u8[]                      y_bits
      u8                        s_claim
    """
    # Header
    out = _be32(len(claim["r"]))
    out += claim["r"]
    out += _be32(claim["r_dot_m_xor_s"])
    out += _pack_list([_be32(gi) for gi in claim["non_reusable"]])

    # Header Merkle path
    hpath_items: List[bytes] = []
    for sibling, is_left in claim["header_merkle_path"]:
        hpath_items.append(_bytes_of_len(sibling, 32) + _be8(1 if is_left else 0))
    out += _pack_list(hpath_items)

    # Spot checks
    sc_items: List[bytes] = []
    for sc in claim["spot_checks"]:
        item = _be32(sc["gate_index"])
        item += _bytes_of_len(sc["k_l"], KEY_LEN)
        item += _bytes_of_len(sc["k_r"], KEY_LEN)
        item += _bytes_of_len(sc["k_o"], KEY_LEN)
        # table: 4 ciphertexts row-major. table is [[ct00, ct01], [ct10, ct11]]
        for row in sc["table"]:
            for ct in row:
                item += _bytes_of_len(ct, KEY_LEN)
        # merkle_path
        mpath_items: List[bytes] = []
        for sibling, is_left in sc["merkle_path"]:
            mpath_items.append(_bytes_of_len(sibling, 32) + _be8(1 if is_left else 0))
        item += _pack_list(mpath_items)
        sc_items.append(item)
    out += _pack_list(sc_items)

    # y_bits + s_claim
    out += _pack_list([_be8(b) for b in claim["y_bits"]])
    out += _be8(claim["s_claim"])
    return out


def claim_hash(claim: dict) -> bytes:
    """SHA-256 of the serialized claim — used as the Verified event's
    `hash_of_claim`."""
    return hashlib.sha256(serialize_claim(claim)).digest()


# ---------------------------------------------------------------------------
# End-to-end demo / golden vector
# ---------------------------------------------------------------------------

def demo(T: int = 2, lam: int = 128, message_size: int = 128) -> dict:
    """Run a full PSetup → PGen → PSolve → serialize round-trip.

    Returns a dict with all four structures + their SHA-256 hashes so
    we can pin them as golden vectors for the Rust parser.
    """
    from timelock_puzzle.tlp_garbling import PythonGarbledTLP  # noqa: E402

    tlp = PythonGarbledTLP(
        lam=lam,
        message_size=message_size,
        T=T,
        use_sha256=False,     # xor_mixing for fast golden vectors
        garbling_mode="prgc",
    )
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)

    spec = build_circuit_spec(tlp)
    meta = build_puzzle_meta(tlp, fee=100)
    puzzle = build_puzzle_from_z(tlp, Z, pp)
    claim = build_claim(tlp, Z, witness, s, y)

    return {
        "spec": spec,
        "spec_bytes": serialize_circuit_spec(spec),
        "spec_hash": circuit_spec_hash(spec),
        "meta": meta,
        "meta_bytes": serialize_puzzle_meta(meta),
        "puzzle": puzzle,
        "puzzle_bytes": serialize_puzzle(puzzle),
        "puzzle_hash": puzzle_hash(puzzle),
        "claim": claim,
        "claim_bytes": serialize_claim(claim),
        "claim_hash": claim_hash(claim),
        "s": s,
        "y": y,
        "verified": tlp.PVerify(s, y, Z),
    }


if __name__ == "__main__":
    d = demo(T=2)
    print(f"spec_bytes:    {len(d['spec_bytes']):4d} B  hash={d['spec_hash'].hex()[:16]}…")
    print(f"meta_bytes:    {len(d['meta_bytes']):4d} B")
    print(f"puzzle_bytes:  {len(d['puzzle_bytes']):4d} B  hash={d['puzzle_hash'].hex()[:16]}…")
    print(f"claim_bytes:   {len(d['claim_bytes']):4d} B  hash={d['claim_hash'].hex()[:16]}…")
    print(f"s={d['s']}, verified={d['verified']}")
