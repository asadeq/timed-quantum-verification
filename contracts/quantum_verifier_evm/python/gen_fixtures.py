#!/usr/bin/env python3
"""
Generate Solidity test fixtures for the EVM verifier from real TLP runs.

This is the bridge between the chain-agnostic Python TLP and the Solidity
verifier. It runs PSetup -> PGen -> PSolve, builds the EVM claim wire format
(see `docs/WIRE_FORMAT_EVM.md`), Merkle-izes the puzzle body,
and emits `test/fixtures/GeneratedFixtures.sol` containing:

  * one fixture per verdict case (honest, and one per rejection reason)
  * `pad()` golden vectors, so the Solidity port of the Yao pad is checked
    against the Python original rather than against itself

The `pad` vectors matter: the Soroban port had a `clone_from_slice` direction
bug that a self-consistent test happily passed. Cross-language vectors with
real bytes are what catch that class of bug.

Usage:
    uv run python contracts/quantum_verifier_evm/python/gen_fixtures.py
"""

from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVM_ROOT = HERE.parent
REPO_ROOT = EVM_ROOT.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "Quantum_vertification_artifact"))

from timelock_puzzle.tlp_garbling import PythonGarbledTLP  # noqa: E402

KEY_LEN = 16
OUT_PATH = EVM_ROOT / "test" / "fixtures" / "GeneratedFixtures.sol"


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------

def be32(n: int) -> bytes:
    return struct.pack(">I", n)


def be64(n: int) -> bytes:
    return struct.pack(">Q", n)


def fixed(b: bytes, n: int) -> bytes:
    """Pad or truncate to exactly n bytes."""
    return b.ljust(n, b"\x00")[:n]


def pad(k_l: bytes, k_r: bytes, gi: int) -> bytes:
    """SHA-256(k_l || k_r || gi_be64)[:16] — mirrors SpotCheck.pad."""
    return hashlib.sha256(k_l + k_r + be64(gi)).digest()[:KEY_LEN]


def select_bit(key: bytes) -> int:
    return key[0] & 1


# ---------------------------------------------------------------------------
# Merkle tree
#
# Clean reimplementation. The Soroban-side `serialize.py::path_for_v2` walks
# the tree by *value* (`target_leaf == left or target_leaf == right`), which
# would append a spurious path element if a hash ever collided with another
# node at the same level. This version walks by *index*, which cannot.
# ---------------------------------------------------------------------------

def build_tree(leaves: list[bytes]) -> tuple[bytes, list[list[bytes]]]:
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        cur = levels[-1]
        nxt = []
        for i in range(0, len(cur), 2):
            left = cur[i]
            right = cur[i + 1] if i + 1 < len(cur) else left
            nxt.append(hashlib.sha256(left + right).digest())
        levels.append(nxt)
    return levels[-1][0], levels


def path_for(levels: list[list[bytes]], idx: int) -> list[tuple[bytes, bool]]:
    """Path from leaf `idx` to the root.

    Returns (sibling, is_left) where is_left=True means the sibling is the
    LEFT child — matching `Merkle.verifyFromCursor`.
    """
    path: list[tuple[bytes, bool]] = []
    for lvl in range(len(levels) - 1):
        cur = levels[lvl]
        if idx % 2 == 0:
            sib = idx + 1 if idx + 1 < len(cur) else idx
            is_left = False  # sibling sits on the right (or is a self-pair)
        else:
            sib = idx - 1
            is_left = True  # sibling sits on the left
        path.append((cur[sib], is_left))
        idx //= 2
    return path


# ---------------------------------------------------------------------------
# Claim construction
# ---------------------------------------------------------------------------

def _puzzle_tree(
    Z: tuple,
    solver: bytes | None = None,
    commitment: bytes | None = None,
) -> tuple[bytes, list[list[bytes]], list[int]]:
    """Build the Merkle tree from generator material alone.

    The client can run this *without solving the TLP*: every leaf input comes
    from `PGen`'s output (`Z`), never from the solver's witness. The `solver`
    address is bound into the header leaf here, at registration time — which
    is why the client must know the server's address before posting the bounty.

    `commitment` = SHA-256(y || s || r) over the *honest* (y, s): the header
    leaf binds it, so the registered root only verifies claims whose output
    and solution bit match the embedded secret. Preimaging it requires
    solving the puzzle.
    """
    if commitment is None:
        raise ValueError("_puzzle_tree requires the registration commitment")
    x_tilde, r, r_dot_m_xor_s = Z
    _encoded_a, _encoded_b, yao_material = x_tilde

    non_reusable = sorted(yao_material["non_reusable"])

    # --- leaves ------------------------------------------------------------
    # The EVM verifier binds the claim to the submitting account: the header
    # leaf includes the solver's 20-byte address, so a claim only verifies
    # from the account it was built for (anti-front-running once a bounty is
    # attached). `solver=None` keeps the Soroban leaf preimage.
    #
    # Only non-reusable gates get leaves, so a valid gate-leaf Merkle proof is
    # itself the non-reusability proof — no bitmap/list needs to travel in the
    # claim (it used to, and its ceil(max_gate_index/8) length was the only
    # T-dependent term in the claim size).
    #
    # The trailing `commitment` binds the embedded secret: the contract
    # recomputes d = SHA-256(y || s_claim || r) from the claim's own fields
    # and folds it into the leaf, so a claim with a wrong output or solution
    # bit fails the header Merkle check (reason 1).
    header_leaf = hashlib.sha256(
        r + be32(r_dot_m_xor_s) + commitment + (solver or b"")).digest()

    gate_leaves: list[bytes] = []
    for gi in non_reusable:
        table = yao_material["tables"][gi]
        flat = b"".join(fixed(ct, KEY_LEN) for row in table for ct in row)
        gate_leaves.append(hashlib.sha256(flat + be32(gi)).digest())

    root, levels = build_tree([header_leaf] + gate_leaves)
    return root, levels, non_reusable


def puzzle_commitment(y: bytes, s: int, r: bytes) -> bytes:
    """d = SHA-256(y || s || r) — the registration-time secret commitment.

    The client knows (m, s, r) at PGen time (it samples m; `tlp.embedded_message`),
    and the honest claim's (y, s_claim) = (m, s). The header leaf binds d, so a
    claim verifies only if it carries the true embedded secret: preimaging d
    requires actually solving the puzzle.
    """
    return hashlib.sha256(y + bytes([s]) + r).digest()


def puzzle_root(Z: tuple, solver: bytes | None = None,
                commitment: bytes | None = None) -> bytes:
    """The on-chain `puzzleHash`: what the client registers (and escrows against).

    `commitment` is the registration-time secret commitment (puzzle_commitment);
    it is bound into the header leaf, so the registered root only verifies
    claims carrying the true (y, s_claim)."""
    if commitment is None:
        raise ValueError("puzzle_root requires the registration commitment")
    return _puzzle_tree(Z, solver, commitment)[0]


def build_claim(
    tlp,
    Z: tuple,
    witness: dict,
    s_claim: int,
    y: bytes,
    spot_check_indices: list[int],
    solver: bytes | None = None,
    commitment: bytes | None = None,
) -> dict:
    """Build a claim bound to the registration-time `commitment`.

    `commitment` = puzzle_commitment over the *honest* (y, s) — the value the
    client registered. Tampered claims (flipped s_claim, wrong y) must still
    be built against the honest commitment so the on-chain leaf check catches
    them; a claim built against its own tampered commitment would be
    self-consistent (the registrant would be scaming only themselves).
    """
    if commitment is None:
        raise ValueError("build_claim requires the registration commitment")
    x_tilde, r, r_dot_m_xor_s = Z
    root, levels, non_reusable = _puzzle_tree(Z, solver, commitment)
    _encoded_a, _encoded_b, yao_material = x_tilde
    header_path = path_for(levels, 0)
    gate_paths = {gi: path_for(levels, 1 + i) for i, gi in enumerate(non_reusable)}

    # --- spot checks -------------------------------------------------------
    spot_checks = []
    for gi in spot_check_indices:
        k_l, k_r, k_o = witness["gate_keys"][gi]
        spot_checks.append({
            "gate_index": gi,
            "k_l": fixed(k_l, KEY_LEN),
            "k_r": fixed(k_r, KEY_LEN),
            "k_o": fixed(k_o, KEY_LEN),
            "table": yao_material["tables"][gi],
            "merkle_path": gate_paths[gi],
        })

    return {
        "r": r,
        "r_dot_m_xor_s": r_dot_m_xor_s,
        "header_path": header_path,
        "spot_checks": spot_checks,
        "y": y,
        "s_claim": s_claim,
        "commitment": commitment,
        "puzzle_hash": root,
    }


def serialize_path(path: list[tuple[bytes, bool]]) -> bytes:
    out = be32(len(path))
    for sib, is_left in path:
        out += fixed(sib, 32) + bytes([1 if is_left else 0])
    return out


def serialize_claim(c: dict) -> bytes:
    out = be32(len(c["r"])) + c["r"]
    out += bytes([c["r_dot_m_xor_s"]])
    out += serialize_path(c["header_path"])

    out += be32(len(c["spot_checks"]))
    for sc in c["spot_checks"]:
        out += be32(sc["gate_index"])
        out += sc["k_l"] + sc["k_r"] + sc["k_o"]
        out += b"".join(fixed(ct, KEY_LEN) for row in sc["table"] for ct in row)
        out += serialize_path(sc["merkle_path"])

    out += be32(len(c["y"])) + c["y"]
    out += bytes([c["s_claim"]])
    return out


# ---------------------------------------------------------------------------
# Fixture generation
# ---------------------------------------------------------------------------

def flip_bit(b: bytes, bit: int) -> bytes:
    ba = bytearray(b)
    ba[bit // 8] ^= 1 << (bit % 8)
    return bytes(ba)


def main() -> None:
    print("==> Running TLP (PRGC, lam=128, msg=128, T=1)")
    tlp = PythonGarbledTLP(
        lam=128, message_size=128, T=1, use_sha256=False, garbling_mode="prgc"
    )
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
    assert tlp.PVerify(s, y, Z), "honest PVerify failed"

    non_reusable = sorted(witness["gate_keys"].keys())
    print(f"    s={s}  |y|={len(y)}B  non_reusable={len(non_reusable)}")

    # The registration-time secret commitment: the honest (y, s) is the pair
    # the client committed to at PGen (y == the embedded message — canary).
    commitment = puzzle_commitment(y, s, Z[1])
    assert y == tlp.embedded_message, "honest output != embedded message"

    # Every fixture claim is bound to this fixed submitting address; the
    # golden-vector test must `vm.prank` the same one. 0x…A11CE ("ALICE").
    SOLVER = bytes.fromhex("00000000000000000000000000000000000A11CE")
    OTHER_SOLVER = bytes.fromhex("0BADC0DE00000000000000000000000000000001")

    fixtures: list[tuple[str, bytes, bytes, bool, int]] = []

    def add(name: str, claim: dict, valid: bool, reason: int) -> None:
        fixtures.append((name, claim["puzzle_hash"], serialize_claim(claim), valid, reason))

    # 1. Honest, K=1
    c = build_claim(tlp, Z, witness, s, y, non_reusable[:1], solver=SOLVER,
                    commitment=commitment)
    add("honest_k1", c, True, 0)

    # 2. Honest, K=8
    c8 = build_claim(tlp, Z, witness, s, y, non_reusable[:8], solver=SOLVER,
                     commitment=commitment)
    add("honest_k8", c8, True, 0)

    # 3. Flipped s_claim -> the leaf's secret commitment no longer matches
    #    the registered root -> reason 1 (header Merkle; the commitment
    #    subsumes the GL check)
    c = build_claim(tlp, Z, witness, s ^ 1, y, non_reusable[:1], solver=SOLVER,
                    commitment=commitment)
    add("bad_s_claim", c, False, 1)

    # 4. Flipped k_o -> reason 3 (Yao spot-check)
    c = build_claim(tlp, Z, witness, s, y, non_reusable[:1], solver=SOLVER,
                    commitment=commitment)
    c["spot_checks"][0]["k_o"] = flip_bit(c["spot_checks"][0]["k_o"], 7)
    add("bad_k_o", c, False, 3)

    # 5. Flipped table byte -> gate leaf changes -> reason 2 (gate Merkle)
    c = build_claim(tlp, Z, witness, s, y, non_reusable[:1], solver=SOLVER,
                    commitment=commitment)
    t = c["spot_checks"][0]["table"]
    t[0][0] = flip_bit(t[0][0], 3)
    add("bad_table", c, False, 2)

    # 6. Flipped r byte -> header leaf changes -> reason 1 (header Merkle)
    c = build_claim(tlp, Z, witness, s, y, non_reusable[:1], solver=SOLVER,
                    commitment=commitment)
    c["r"] = flip_bit(c["r"], 5)
    add("bad_r", c, False, 1)

    # 7. Unknown puzzle id -> reason 0
    c = build_claim(tlp, Z, witness, s, y, non_reusable[:1], solver=SOLVER,
                    commitment=commitment)
    add("unknown_puzzle", c, False, 0)

    # 8. Right claim, wrong submitting account -> the header leaf no longer
    #    resolves to puzzleHash -> reason 1 (anti-front-running)
    c = build_claim(tlp, Z, witness, s, y, non_reusable[:1], solver=OTHER_SOLVER,
                    commitment=commitment)
    add("wrong_solver", c, False, 1)

    # 9. Wrong output with a coset-consistent s_claim: the GL parity check
    #    alone would accept this pair (any y' has a matching s'), but the
    #    leaf's secret commitment does not -> reason 1. This is the case the
    #    commitment check exists for.
    y_bad = flip_bit(y, 11)
    r_int = int.from_bytes(Z[1], "big")
    y_int = int.from_bytes(y_bad, "big")
    s_consistent = Z[2] ^ (bin(r_int & y_int).count("1") % 2)
    c = build_claim(tlp, Z, witness, s_consistent, y_bad, non_reusable[:1],
                    solver=SOLVER, commitment=commitment)
    add("bad_y_consistent_s", c, False, 1)

    # --- pad golden vectors ------------------------------------------------
    pad_vectors = []
    for i, gi in enumerate(non_reusable[:4]):
        k_l, k_r, _ = witness["gate_keys"][gi]
        pad_vectors.append((fixed(k_l, KEY_LEN), fixed(k_r, KEY_LEN), gi, pad(k_l, k_r, gi)))
    # A couple of synthetic ones with high bytes, to catch sign/alignment bugs.
    for gi in (0, 1, 0xFFFFFFFF):
        k_l = bytes(range(16))
        k_r = bytes(range(16, 32))
        pad_vectors.append((k_l, k_r, gi, pad(k_l, k_r, gi)))

    write_solidity(fixtures, pad_vectors)
    print(f"==> Wrote {OUT_PATH} ({len(fixtures)} fixtures, {len(pad_vectors)} pad vectors)")


def write_solidity(
    fixtures: list[tuple[str, bytes, bytes, bool, int]],
    pad_vectors: list[tuple[bytes, bytes, int, bytes]],
) -> None:
    lines = [
        "// SPDX-License-Identifier: MIT",
        "// AUTO-GENERATED by python/gen_fixtures.py — do not edit by hand.",
        "pragma solidity ^0.8.24;",
        "",
        "library GeneratedFixtures {",
        "    struct Fixture {",
        "        string name;",
        "        bytes32 puzzleHash;",
        "        bytes claim;",
        "        bool expectValid;",
        "        uint8 expectReason;",
        "    }",
        "",
        "    struct PadVector {",
        "        bytes16 kL;",
        "        bytes16 kR;",
        "        uint32 gateIndex;",
        "        bytes16 expected;",
        "    }",
        "",
        f"    function all() internal pure returns (Fixture[] memory f) {{",
        f"        f = new Fixture[]({len(fixtures)});",
    ]
    for i, (name, ph, claim, valid, reason) in enumerate(fixtures):
        lines.append(
            f'        f[{i}] = Fixture("{name}", bytes32(hex"{ph.hex()}"), '
            f'hex"{claim.hex()}", {"true" if valid else "false"}, {reason});'
        )
    lines += [
        "    }",
        "",
        f"    function padVectors() internal pure returns (PadVector[] memory p) {{",
        f"        p = new PadVector[]({len(pad_vectors)});",
    ]
    for i, (k_l, k_r, gi, expected) in enumerate(pad_vectors):
        lines.append(
            f'        p[{i}] = PadVector(bytes16(hex"{k_l.hex()}"), '
            f'bytes16(hex"{k_r.hex()}"), {gi}, bytes16(hex"{expected.hex()}"));'
        )
    lines += ["    }", "}", ""]

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text("\n".join(lines))


if __name__ == "__main__":
    main()
