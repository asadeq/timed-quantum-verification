"""Yao garbling helpers for PRGC mode (SHA-256 PRF, dependency-free).

Each wire w carries a pair of per-bit keys (K_w^0, K_w^1). A garbled gate
stores 4 ciphertexts, one per (left_bit, right_bit) pair; the PSolver uses
the two delivered input-wire keys to decrypt and recover the output bit.
See README §"Garbling modes" for how these primitives fit into PRGC.
"""

import hashlib
import secrets


KEY_LEN = 16  # 128-bit per-wire keys


def gen_key() -> bytes:
    """Generate one Yao per-wire key (128 bits)."""
    return secrets.token_bytes(KEY_LEN)


def _combined_key(k_left: bytes, k_right: bytes) -> bytes:
    """XOR the two parent keys (length-padded if needed)."""
    L = max(len(k_left), len(k_right))
    a = k_left.ljust(L, b"\x00")
    b = k_right.ljust(L, b"\x00")
    return bytes(x ^ y for x, y in zip(a, b))


def garble_bit(bit: bool, k_left: bytes, k_right: bytes) -> bool:
    """Double-key encryption: ciphertext_bit = PRF(K_left XOR K_right)>>7 XOR bit."""
    combined = _combined_key(k_left, k_right)
    prf_byte = hashlib.sha256(combined).digest()[0]
    return bool((prf_byte >> 7) ^ (1 if bit else 0))


def ungarble_bit(ciphertext: bool, k_left: bytes, k_right: bytes) -> bool:
    """Reverse of garble_bit."""
    combined = _combined_key(k_left, k_right)
    prf_byte = hashlib.sha256(combined).digest()[0]
    return bool((prf_byte >> 7) ^ (1 if ciphertext else 0))


def derive_output_key(output_bit: bool, k_left: bytes, k_right: bytes) -> bytes:
    """Per-wire key for the recovered output (unused in CRGC; kept for symmetry)."""
    return hashlib.sha256(_combined_key(k_left, k_right)).digest()[:KEY_LEN]


def gen_key_with_select_bit(select_bit: int) -> bytes:
    """Random 128-bit key whose LSB of the first byte is the select bit.

    Used by point-and-permute garbling: the LSB of the first byte tells the
    evaluator which row of the garbled table to decrypt without leaking the
    underlying wire value.
    """
    k = bytearray(secrets.token_bytes(KEY_LEN))
    k[0] = (k[0] & 0xFE) | (select_bit & 1)
    return bytes(k)


def select_bit(key: bytes) -> int:
    """Return the point-and-permute select bit encoded in `key`'s first byte."""
    return key[0] & 1


def pad(k_left: bytes, k_right: bytes, gate_index: int) -> bytes:
    """Per-(gate, row) one-time pad derived from the two parent keys.

    The gate index is mixed in so the same pair of parent keys yields four
    independent pads across the four input combinations (00, 01, 10, 11).
    """
    return hashlib.sha256(
        k_left + k_right + gate_index.to_bytes(8, "big")
    ).digest()[:KEY_LEN]


def xor_bytes(a: bytes, b: bytes) -> bytes:
    """XOR two byte strings (truncated to the shorter length)."""
    return bytes(x ^ y for x, y in zip(a, b))


def pack_bits(bits: list[int]) -> bytes:
    """Pack bits LSB-first (same convention as bits_to_bytes)."""
    out = bytearray()
    for i in range(0, len(bits), 8):
        byte_val = 0
        for j, bit in enumerate(bits[i:i + 8]):
            if bit:
                byte_val |= (1 << j)
        out.append(byte_val)
    return bytes(out)


def unlock_key(packed_preimage: bytes) -> bytes:
    """K_unlock = SHA256(domain-separator || packed boundary wire values).

    Used by TLP4 PRGC mode to seal the per-puzzle Yao boundary keys behind a
    hash of the sequential chain's output wire values. In the random-oracle
    model the solver can only recover K_unlock after performing the T
    sequential evaluations.
    """
    return hashlib.sha256(b"TLP4-UNLOCK" + packed_preimage).digest()[:KEY_LEN]


def boundary_mask(k_unlock: bytes, wire: int) -> bytes:
    """Per-wire mask used to encrypt the boundary key for `wire`."""
    return hashlib.sha256(k_unlock + wire.to_bytes(8, "big")).digest()[:KEY_LEN]


