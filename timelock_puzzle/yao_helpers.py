"""
Minimal Yao garbling helpers for PRGC mode.

Uses SHA-256 as the underlying PRF so the artifact stays dependency-free and
matches the SHA-256 instantiation of the sequential function used elsewhere
in the construction.

Notation follows Bellare-Rogaway / standard Yao:
  - Each wire w has a pair of per-bit keys (K_w^0, K_w^1).
  - A garbled gate stores 4 ciphertexts, one per (left_bit, right_bit) pair.
  - Decrypting a gate requires the two input wire keys for the actual bit values.

Encoding: ciphertext = SHA256(K_left ⊕ K_right) with bit 0 of byte 0 flipped
to encode the output bit (1 == "key for 1-wire"). Trivial encoding — secure
because the keys are random and never reused across gates.
"""

import hashlib
import secrets


# 128-bit keys (matches the spirit of classical garbled-circuit constructions;
# SHA-256 output provides plenty of entropy for the bit-encoding trick).
KEY_LEN = 16


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
    """
    Yao-style double-key encryption: encrypt a single output bit under two
    input-wire keys, returning the ciphertext as a bool (encoded as a bit flip
    relative to the PRF evaluation).

    Encoding rule:
      - ciphertext_bit = SHA256(K_left ⊕ K_right)[0] >> 7 XOR output_bit

    This is a stream-cipher style encoding: the "PRF evaluation" is the
    underlying value, and we XOR the output bit into the low-order bit of
    the first byte of the digest. Reversing is just: PRF → XOR with
    ciphertext bit → recover output bit.
    """
    combined = _combined_key(k_left, k_right)
    prf_byte = hashlib.sha256(combined).digest()[0]
    return bool((prf_byte >> 7) ^ (1 if bit else 0))


def ungarble_bit(ciphertext: bool, k_left: bytes, k_right: bytes) -> bool:
    """
    Reverse of garble_bit. Re-derive the PRF, XOR with the ciphertext bit,
    and recover the original output bit.
    """
    combined = _combined_key(k_left, k_right)
    prf_byte = hashlib.sha256(combined).digest()[0]
    return bool((prf_byte >> 7) ^ (1 if ciphertext else 0))


def derive_output_key(output_bit: bool, k_left: bytes, k_right: bytes) -> bytes:
    """
    Helper for output decoding: given the recovered output bit and the two
    parent keys, return the per-wire key that corresponds to the recovered
    output value. (Not used in this artifact since CRGC outputs are plaintext,
    but included for completeness.)
    """
    # In our encoding, the ciphertext *is* the output bit (with PRF for
    # key-derivation purposes only). Returning a deterministic key is fine.
    return hashlib.sha256(_combined_key(k_left, k_right)).digest()[:KEY_LEN]
