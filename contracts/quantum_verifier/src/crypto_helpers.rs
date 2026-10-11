//! 1:1 port of [yao_helpers.py](../../../../Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py).
//!
//! All functions are deterministic, side-effect-free, and call the
//! Soroban `env.crypto().sha256` host function for hashing.

use soroban_sdk::{Bytes, BytesN, Env};

/// 128-bit Yao per-wire key length.
pub const KEY_LEN: usize = 16;

/// Per-(gate, row) one-time pad derived from the two parent keys.
///
/// Equivalent to Python `pad(k_left, k_right, gate_index)`:
/// `SHA-256(k_left || k_right || gate_index.to_bytes(8, "big"))[:16]`.
pub fn pad(env: &Env, k_left: &BytesN<16>, k_right: &BytesN<16>, gate_index: u32) -> BytesN<16> {
    let mut preimage = Bytes::new(env);
    preimage.append(&Bytes::from_array(env, &k_left.to_array()));
    preimage.append(&Bytes::from_array(env, &k_right.to_array()));
    // 8-byte big-endian gate index
    let gi_bytes = gate_index.to_be_bytes();
    let mut padded = [0u8; 8];
    padded[4..].copy_from_slice(&gi_bytes);
    preimage.append(&Bytes::from_array(env, &padded));
    let digest: BytesN<32> = env.crypto().sha256(&preimage).into();
    // NB: clone_from_slice copies *from the argument into self*, so the
    // digest slice is the SOURCE here.
    let mut out = [0u8; KEY_LEN];
    out.clone_from_slice(&digest.to_array()[..KEY_LEN]);
    BytesN::from_array(env, &out)
}

/// XOR two byte strings, truncated to the shorter length.
///
/// Equivalent to Python `xor_bytes(a, b)`.
pub fn xor_bytes(env: &Env, a: &BytesN<16>, b: &BytesN<16>) -> BytesN<16> {
    let mut out = [0u8; KEY_LEN];
    for i in 0..KEY_LEN {
        out[i] = a.to_array()[i] ^ b.to_array()[i];
    }
    BytesN::from_array(env, &out)
}

/// Return the point-and-permute select bit encoded in the key's first byte.
///
/// Equivalent to Python `select_bit(key)`.
pub fn select_bit(key: &BytesN<16>) -> u32 {
    (key.to_array()[0] & 1) as u32
}

/// Pack bits LSB-first (same convention as `_bits_to_bytes`).
///
/// Equivalent to Python `pack_bits(bits)`. Reserved for the Phase 4
/// re-derive feature.
#[allow(dead_code)]
pub fn pack_bits(env: &Env, bits: &[u32]) -> Bytes {
    let mut out = Bytes::new(env);
    let mut i = 0;
    while i < bits.len() {
        let mut byte_val: u8 = 0;
        let end = (i + 8).min(bits.len());
        for (j, &bit) in bits[i..end].iter().enumerate() {
            if bit != 0 {
                byte_val |= 1 << j;
            }
        }
        out.push_back(byte_val);
        i += 8;
    }
    out
}

/// `K_unlock = SHA256("TLP4-UNLOCK" || packed_preimage)[:16]`.
///
/// Equivalent to Python `unlock_key(packed_preimage)`. Reserved for the
/// Phase 4 re-derive feature where the solver submits the boundary wire
/// values and the contract re-derives K_unlock itself.
#[allow(dead_code)]
pub fn unlock_key(env: &Env, packed_preimage: &Bytes) -> BytesN<16> {
    let mut preimage = Bytes::new(env);
    preimage.append(&Bytes::from_slice(env, b"TLP4-UNLOCK"));
    preimage.append(&packed_preimage.clone());
    let digest: BytesN<32> = env.crypto().sha256(&preimage).into();
    let mut out = [0u8; KEY_LEN];
    out.clone_from_slice(&digest.to_array()[..KEY_LEN]);
    BytesN::from_array(env, &out)
}

/// Per-wire mask used to encrypt the boundary key for `wire`.
///
/// Equivalent to Python `boundary_mask(k_unlock, wire)`:
/// `SHA-256(k_unlock || wire.to_bytes(8, "big"))[:16]`. Reserved for the
/// Phase 4 re-derive feature.
#[allow(dead_code)]
pub fn boundary_mask(env: &Env, k_unlock: &BytesN<16>, wire: u32) -> BytesN<16> {
    let mut preimage = Bytes::new(env);
    preimage.append(&Bytes::from_array(env, &k_unlock.to_array()));
    let wire_bytes = wire.to_be_bytes();
    let mut padded = [0u8; 8];
    padded[4..].copy_from_slice(&wire_bytes);
    preimage.append(&Bytes::from_array(env, &padded));
    let digest: BytesN<32> = env.crypto().sha256(&preimage).into();
    let mut out = [0u8; KEY_LEN];
    out.clone_from_slice(&digest.to_array()[..KEY_LEN]);
    BytesN::from_array(env, &out)
}
