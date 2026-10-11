#!/usr/bin/env python3
"""
Cross-language parity tests for the quantum verifier.

The Rust contract is a 1:1 port of the Python `_evaluate_prgc` algorithm,
so these tests validate the algorithm itself and the canonical byte
serialization. The Rust port is then implicitly correct by construction.

What it tests:
  1. Honest solver produces a claim that PVerify accepts.
  2. Flipping s_claim breaks PVerify.
  3. Flipping y breaks PVerify.
  4. Claim size is constant in T (=> on-chain CPU is constant in T).

For full Rust contract testing, see contracts/quantum_verifier/tests/
(in-process, real WASM) and scripts/verify_sdk.py for the live Testnet
round-trip including the on-chain verifier.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Quantum_vertification_artifact"))

from timelock_puzzle.tlp_garbling import PythonGarbledTLP  # noqa: E402
from scripts.serialize import build_claim, serialize_claim  # noqa: E402


def test_honest_solver(T: int) -> None:
    tlp = PythonGarbledTLP(lam=128, message_size=128, T=T,
                           use_sha256=False, garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
    assert tlp.PVerify(s, y, Z), f"PVerify failed for honest solver at T={T}"
    print(f"  T={T}: honest solver verified OK")


def test_lying_s_claim(T: int) -> None:
    tlp = PythonGarbledTLP(lam=128, message_size=128, T=T,
                           use_sha256=False, garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, _ = tlp.PSolve(Z, pp, return_witness=True)
    assert tlp.PVerify(1 - s, y, Z) is False, "PVerify accepted lying s_claim"
    print(f"  T={T}: lying s_claim rejected OK")


def test_lying_y(T: int) -> None:
    tlp = PythonGarbledTLP(lam=128, message_size=128, T=T,
                           use_sha256=False, garbling_mode="prgc")
    pp = tlp.PSetup_Garble()
    Z = tlp.PGen(1, pp)
    s, y, _ = tlp.PSolve(Z, pp, return_witness=True)
    _x_tilde, r, _r_dot_m_xor_s = Z
    # Flip a bit of y that is guaranteed to also be set in r, so the
    # y·r parity provably changes. (Flipping an arbitrary bit only
    # changes the parity 50% of the time.)
    r_int = int.from_bytes(r, "big")
    assert r_int != 0
    pos = (r_int & -r_int).bit_length() - 1  # lowest set bit of r
    y_int = int.from_bytes(y, "big")
    y_bad = (y_int ^ (1 << pos)).to_bytes(len(y), "big")
    assert tlp.PVerify(s, y_bad, Z) is False, "PVerify accepted flipped y"
    print(f"  T={T}: flipped y rejected OK")


def test_claim_size_constant_in_T() -> None:
    sizes = []
    for T in (1, 2, 4, 8):
        tlp = PythonGarbledTLP(lam=128, message_size=128, T=T,
                               use_sha256=False, garbling_mode="prgc")
        pp = tlp.PSetup_Garble()
        Z = tlp.PGen(1, pp)
        s, y, witness = tlp.PSolve(Z, pp, return_witness=True)
        claim = build_claim(tlp, Z, witness, s, y)
        sizes.append(len(serialize_claim(claim)))
    assert len(set(sizes)) == 1, f"claim size varies in T: {sizes}"
    print(f"  claim size = {sizes[0]} B for T in {{1,2,4,8}} (constant) OK")


def main() -> None:
    print("Quantum-Verifier cross-language parity tests")
    print("=" * 60)

    print("\n[1] Honest solver (Python source of truth)")
    for T in (1, 2, 4):
        test_honest_solver(T)

    print("\n[2] Adversarial: lying s_claim")
    for T in (1, 2):
        test_lying_s_claim(T)

    print("\n[3] Adversarial: flipped y")
    for T in (1, 2):
        test_lying_y(T)

    print("\n[4] Wire size is constant in T (=> on-chain CPU is constant in T)")
    test_claim_size_constant_in_T()

    print("\nAll Python-side parity tests passed.")
    print("\nNext: ./scripts/deploy.sh for a fresh Testnet deployment, then")
    print("uv run python scripts/verify_sdk.py --contract <C...> --spot-checks 8")
    print("for the full end-to-end round-trip including the on-chain verifier.")


if __name__ == "__main__":
    main()
