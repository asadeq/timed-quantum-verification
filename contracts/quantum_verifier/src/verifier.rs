//! The public entry point: `submit_and_verify`.
//!
//! The puzzle body is **off-chain**. The contract stores only its
//! SHA-256 commitment (`puzzle_hash`). Each `submit_and_verify` call
//! submits a `Claim` that carries:
//!
//! 1. The Goldreich-Levin header (`r`, `r_dot_m_xor_s`, `non_reusable`)
//!    plus a Merkle proof binding them to `puzzle_hash`.
//! 2. K `SpotCheckProof` entries — each with the gate's garbled table and
//!    a Merkle proof binding it to `puzzle_hash`.
//! 3. The circuit output bits (`y_bits`) and claimed bit (`s_claim`).
//!
//! Verification steps:
//! 1. Merkle-bind the header and every spot-checked gate to
//!    `puzzle_hash`. Anything not proven to be part of the registered
//!    puzzle is rejected.
//! 2. Run the Yao decryption check on each spot-checked gate.
//! 3. Goldreich-Levin linear post-processing:
//!    `gf2(r, y) ⊕ s_claim == r_dot_m_xor_s`.

use soroban_sdk::{contract, contracterror, contractimpl, Bytes, BytesN, Env};

use crate::inner_product::{bytes_to_bits_u32, gf2_inner_product};
use crate::merkle::verify_merkle;
use crate::spot_check::verify_spot_check;
use crate::store::{
    add_to_total_collected, clear_payment_token, increment_puzzle_count, read_admin,
    read_fee_per_verify, read_payment_token, read_puzzle_count, read_puzzle_meta,
    read_total_collected, write_admin, write_fee_per_verify, write_payment_token,
    write_puzzle_meta,
};
use crate::types::{Claim, ClaimHeader, CircuitSpec, PuzzleMeta, SpotCheckProof};

#[contract]
pub struct QuantumVerifier;

/// Error code emitted when `read_admin` is called before `init`.
#[contracterror]
#[derive(Copy, Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub enum VerifierError {
    AdminNotSet = 1,
    PuzzleNotFound = 2,
}

/// Compute the Merkle leaf hash for a single gate's spot-check material.
/// leaf = SHA-256( table || gate_index_be32 )
fn gate_leaf_hash(env: &Env, sc: &SpotCheckProof) -> BytesN<32> {
    let mut preimage: Bytes = Bytes::new(env);
    for ct in [&sc.table.0, &sc.table.1, &sc.table.2, &sc.table.3] {
        let b = Bytes::from_array(env, &ct.to_array());
        preimage.append(&b);
    }
    let gi = sc.gate_index;
    preimage.append(&Bytes::from_array(env, &gi.to_be_bytes()));
    env.crypto().sha256(&preimage).into()
}

/// Compute the Merkle leaf hash for the header material.
/// leaf = SHA-256( r || r_dot_m_xor_s || non_reusable_canonical )
fn header_leaf_hash(env: &Env, h: &ClaimHeader) -> BytesN<32> {
    let mut preimage: Bytes = Bytes::new(env);
    preimage.append(&h.r);
    preimage.append(&Bytes::from_array(
        env,
        &h.r_dot_m_xor_s.to_be_bytes(),
    ));
    for gi in h.non_reusable.iter() {
        preimage.append(&Bytes::from_array(env, &gi.to_be_bytes()));
    }
    env.crypto().sha256(&preimage).into()
}

#[contractimpl]
impl QuantumVerifier {
    /// Initialize the contract.
    ///
    /// Sets the admin, the payment token (SAC), and the global per-verify fee.
    /// Pass `payment_token = None` to run the contract in free mode (no fee
    /// collection — useful for demos and Testnet).
    pub fn init(
        env: Env,
        admin: soroban_sdk::Address,
        payment_token: Option<soroban_sdk::Address>,
        fee_per_verify: i128,
    ) {
        admin.require_auth();
        write_admin(&env, &admin);
        match payment_token {
            Some(token) => write_payment_token(&env, &token),
            None => clear_payment_token(&env),
        }
        write_fee_per_verify(&env, fee_per_verify);
    }

    /// Register a new puzzle (admin only).
    ///
    /// Only the *commitment* to the puzzle is stored (`puzzle_hash`). The
    /// puzzle body itself stays off-chain. Returns the new puzzle_id.
    pub fn register_puzzle(
        env: Env,
        spec: CircuitSpec,
        circuit_hash: BytesN<32>,
        pk_commitment: BytesN<32>,
        puzzle_hash: BytesN<32>,
        fee: u32,
    ) -> u32 {
        let _ = spec;
        let admin = read_admin(&env);
        admin.require_auth();

        let puzzle_id = increment_puzzle_count(&env);
        let meta = PuzzleMeta {
            circuit_hash,
            pk_commitment,
            puzzle_hash,
            fee,
        };
        write_puzzle_meta(&env, puzzle_id, &meta);

        env.events().publish(
            ("quantum_verifier", "puzzle_registered"),
            (puzzle_id, fee),
        );
        puzzle_id
    }

    /// Submit and verify a claim.
    ///
    /// All puzzle material lives inside `claim` and is Merkle-bound to
    /// the registered `puzzle_hash`. Returns true iff:
    ///   1. Every Merkle proof yields `meta.puzzle_hash`.
    ///   2. Every spot-checked gate passes the Yao decryption check.
    ///   3. `gf2(r, y) ⊕ s_claim == r_dot_m_xor_s`.
    pub fn submit_and_verify(
        env: Env,
        caller: soroban_sdk::Address,
        puzzle_id: u32,
        claim: Claim,
    ) -> bool {
        caller.require_auth();

        // Pull the fee (only if both fee > 0 and a payment token is set).
        let fee = read_fee_per_verify(&env);
        if fee > 0 && read_payment_token(&env).is_some() {
            let token = read_payment_token(&env).unwrap();
            let token_client = soroban_sdk::token::Client::new(&env, &token);
            token_client.transfer(&caller, &env.current_contract_address(), &fee);
            add_to_total_collected(&env, fee);
        }

        // Pull the meta. If the puzzle isn't registered, reject.
        let meta = match read_puzzle_meta(&env, puzzle_id) {
            Some(m) => m,
            None => {
                env.events().publish(
                    ("quantum_verifier", "rejected"),
                    (puzzle_id, caller.clone(), 0u32),
                );
                return false;
            }
        };

        // Step 1a: Merkle-bind the header to puzzle_hash.
        let header_leaf = header_leaf_hash(&env, &claim.header);
        let header_ok = verify_merkle(
            &env,
            &header_leaf,
            &claim.header.merkle_path,
            &meta.puzzle_hash,
        );
        if !header_ok {
            env.events().publish(
                ("quantum_verifier", "rejected"),
                (puzzle_id, caller.clone(), 1u32), // reason 1 = bad header Merkle
            );
            return false;
        }

        // Step 1b: Merkle-bind every spot-checked gate to puzzle_hash.
        for sc in claim.spot_checks.iter() {
            let leaf = gate_leaf_hash(&env, &sc);
            let ok = verify_merkle(&env, &leaf, &sc.merkle_path, &meta.puzzle_hash);
            if !ok {
                env.events().publish(
                    ("quantum_verifier", "rejected"),
                    (puzzle_id, caller.clone(), 2u32), // reason 2 = bad gate Merkle
                );
                return false;
            }
        }

        // Step 2: TLP spot-check math (Yao decryption for K gates).
        let spot_ok = verify_spot_check(
            &env,
            &claim.header.non_reusable,
            &claim.spot_checks,
        );
        if !spot_ok {
            env.events().publish(
                ("quantum_verifier", "rejected"),
                (puzzle_id, caller.clone(), 3u32), // reason 3 = bad spot-check
            );
            return false;
        }

        // Step 3: Goldreich-Levin linear post-processing.
        let r_bits = bytes_to_bits_u32(&claim.header.r);
        let y_bits = claim.y_bits.clone();
        let y_dot_r = gf2_inner_product(&r_bits, &y_bits);
        let lhs = y_dot_r ^ claim.s_claim;
        let rhs = claim.header.r_dot_m_xor_s;
        if lhs != rhs {
            env.events().publish(
                ("quantum_verifier", "rejected"),
                (puzzle_id, caller.clone(), 4u32), // reason 4 = bad GL check
            );
            return false;
        }

        env.events().publish(
            ("quantum_verifier", "verified"),
            (puzzle_id, caller, claim.s_claim),
        );
        true
    }

    /// Admin: withdraw accumulated fees to `to`.
    pub fn withdraw(env: Env, to: soroban_sdk::Address) {
        let admin = read_admin(&env);
        admin.require_auth();

        let amount = read_total_collected(&env);
        if amount > 0 {
            if let Some(token) = read_payment_token(&env) {
                let token_client = soroban_sdk::token::Client::new(&env, &token);
                token_client.transfer(&env.current_contract_address(), &to, &amount);
            }
        }
    }

    /// Read the current puzzle count.
    pub fn puzzle_count(env: Env) -> u32 {
        read_puzzle_count(&env)
    }

    /// Read a puzzle's metadata.
    pub fn puzzle_meta(env: Env, puzzle_id: u32) -> Option<PuzzleMeta> {
        read_puzzle_meta(&env, puzzle_id)
    }
}