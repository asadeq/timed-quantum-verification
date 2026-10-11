//! TLP spot-check — verify K random non-reusable gate decryptions.
//!
//! For each `(gate_index, table, (k_l, k_r, k_o))` triple provided by the
//! solver, verify:
//!
//! ```text
//! a = select_bit(k_l)
//! b = select_bit(k_r)
//! ct = table[a*2 + b]
//! expected_k_o = xor_bytes(ct, pad(k_l, k_r, gate_index))
//! provided_k_o == expected_k_o
//! ```
//!
//! The tables live inside `Claim.spot_checks` and are bound to the
//! registered `puzzle_hash` via per-gate Merkle proofs (verified by the
//! caller before this function is invoked).

use soroban_sdk::{BytesN, Env, Vec};

use crate::crypto_helpers::{pad, select_bit, xor_bytes};
use crate::types::SpotCheckProof;

/// Look up the ciphertext at (a, b) in a 4-entry row-major table.
fn table_entry<'a>(
    table: &'a (BytesN<16>, BytesN<16>, BytesN<16>, BytesN<16>),
    a: u32,
    b: u32,
) -> &'a BytesN<16> {
    match a * 2 + b {
        0 => &table.0,
        1 => &table.1,
        2 => &table.2,
        _ => &table.3,
    }
}

/// Verify the TLP spot-check.
///
/// Returns true iff every entry passes the Yao decryption check.
///
/// `non_reusable` is the sorted list of gate indices declared in the claim
/// header — `gate_index` values must appear in it.
pub fn verify_spot_check(
    env: &Env,
    non_reusable: &Vec<u32>,
    spot_checks: &Vec<SpotCheckProof>,
) -> bool {
    for sc in spot_checks.iter() {
        // gate_index must be in the non_reusable set
        let pos = non_reusable.iter().position(|x| x == sc.gate_index);
        if pos.is_none() {
            return false;
        }
        let a = select_bit(&sc.k_l);
        let b = select_bit(&sc.k_r);
        let ct = table_entry(&sc.table, a, b);
        let expected_k_o = xor_bytes(env, ct, &pad(env, &sc.k_l, &sc.k_r, sc.gate_index));
        if expected_k_o != sc.k_o {
            return false;
        }
        if expected_k_o != sc.k_o {
            return false;
        }
        let expected_k_o = xor_bytes(env, ct, &pad(env, &sc.k_l, &sc.k_r, sc.gate_index));
        if expected_k_o != sc.k_o {
            return false;
        }
    }
    true
}