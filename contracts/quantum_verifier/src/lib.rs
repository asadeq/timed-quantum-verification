//! On-chain claim verifier for Quantum-Verification-as-a-Service.
//!
//! The contract does **not** re-solve the TLP and never sees the puzzle
//! body. The body is Merkle-ized off-chain; `register_puzzle` stores only
//! the root. `submit_and_verify` then checks a claim:
//!
//! 1. Merkle-bind the claim header and every spot-checked gate table to
//!    the registered `puzzle_hash` (O(log N) SHA-256 calls).
//! 2. Spot-check K non-reusable gates of the TLP's PRGC section
//!    (~K SHA-256 + K XORs).
//! 3. Linear post-processing: `gf2(r, y) ⊕ s_claim == r_dot_m_xor_s`
//!    (one GF(2) inner product).
//!
//! See [STELLAR_SERVICE.md](../../STELLAR_SERVICE.md) for the full design
//! and [SPEC.md](../../SPEC.md) for the wire format.

#![no_std]

pub mod crypto_helpers;
mod inner_product;
mod merkle;
mod spot_check;
mod store;
mod types;
mod verifier;

pub use types::*;
pub use verifier::*;
