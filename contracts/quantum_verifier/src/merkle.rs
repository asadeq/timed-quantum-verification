//! SHA-256 Merkle proof verification.
//!
//! Given a 32-byte leaf, a path of (sibling, is_left) pairs, and a
//! 32-byte root, recompute the root and compare.

use soroban_sdk::{BytesN, Env, Vec};

/// Verify a Merkle proof.
///
/// Returns true iff hashing `leaf` up the `path` produces `root`.
pub fn verify_merkle(
    env: &Env,
    leaf: &BytesN<32>,
    path: &Vec<(BytesN<32>, bool)>,
    root: &BytesN<32>,
) -> bool {
    let mut current = leaf.clone();
    for (sibling, is_left) in path.iter() {
        let mut preimage = soroban_sdk::Bytes::new(env);
        let sib_bytes = soroban_sdk::Bytes::from_array(env, &sibling.to_array());
        let cur_bytes = soroban_sdk::Bytes::from_array(env, &current.to_array());
        if is_left {
            // current is the right child; sibling is on the left.
            preimage.append(&sib_bytes);
            preimage.append(&cur_bytes);
        } else {
            // current is the left child; sibling is on the right.
            preimage.append(&cur_bytes);
            preimage.append(&sib_bytes);
        }
        current = env.crypto().sha256(&preimage).into();
    }
    current == *root
}
