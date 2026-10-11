//! GF(2) inner product over bit vectors.
//!
//! Used for the Goldreich-Levin unmasking step:
//! `s = r·m ⊕ y·r  ⟺  parity(r ∧ m) ⊕ parity(r ∧ y) == r·m ⊕ s`.
//!
//! The bits are packed LSB-first, matching the Python convention in
//! [`yao_helpers.py`](../../../../Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py).

use soroban_sdk::{Bytes, Vec};

/// Compute the GF(2) inner product of two Soroban `Vec<u32>` bit vectors.
///
/// Each entry must be 0 or 1. Returns the parity of the bitwise AND.
pub fn gf2_inner_product(a: &Vec<u32>, b: &Vec<u32>) -> u32 {
    let mut acc: u32 = 0;
    let n = a.len().min(b.len());
    for i in 0..n {
        acc ^= a.get(i).unwrap() & b.get(i).unwrap();
    }
    // parity of the accumulated u32
    acc.count_ones() & 1
}

/// Convert an LSB-first `Bytes` blob to a `Vec<u32>` bit vector.
///
/// Each byte of the input is expanded to 8 bits, LSB first. The output
/// has length `8 * bytes.len()`.
pub fn bytes_to_bits_u32(bytes: &Bytes) -> Vec<u32> {
    let mut out = Vec::new(bytes.env());
    for byte in bytes.iter() {
        for i in 0..8 {
            out.push_back(((byte >> i) & 1) as u32);
        }
    }
    out
}
