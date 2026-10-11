//! Integration test: build a `Puzzle`, hash it, register the hash, then
//! submit a `Claim` with Merkle proofs that bind the header and the
//! spot-checked gate back to the registered `puzzle_hash`.
//!
//! We construct a real 2-leaf Merkle tree:
//!   leaf_H = SHA-256(header_preimage)
//!   leaf_G = SHA-256(gate_preimage)
//!   root   = SHA-256(leaf_H || leaf_G)
//! Then `puzzle_hash = root` and each Merkle path is the single sibling.
//!
//! Run with: cargo test --release -p quantum_verifier --test integration_register -- --nocapture

use quantum_verifier::{Claim, ClaimHeader, CircuitSpec, QuantumVerifierClient, SpotCheckProof};
use soroban_sdk::{testutils::Address as _, testutils::Events, Address, Bytes, BytesN, Env, Vec};

static WASM: &[u8] = include_bytes!(
    "../target/wasm32v1-none/release/quantum_verifier.optimized.wasm"
);

/// SHA-256 of the concatenation of `a || b`. Used to combine Merkle nodes.
fn sha256_concat(env: &Env, a: &BytesN<32>, b: &BytesN<32>) -> BytesN<32> {
    let mut preimage = Bytes::new(env);
    preimage.append(&Bytes::from_array(env, &a.to_array()));
    preimage.append(&Bytes::from_array(env, &b.to_array()));
    env.crypto().sha256(&preimage).into()
}

/// Recompute the header leaf hash the way the contract does it.
fn compute_header_leaf(
    env: &Env,
    r: &Bytes,
    r_dot_m_xor_s: u32,
    non_reusable: &Vec<u32>,
) -> BytesN<32> {
    let mut preimage = Bytes::new(env);
    preimage.append(r);
    preimage.append(&Bytes::from_array(env, &r_dot_m_xor_s.to_be_bytes()));
    for gi in non_reusable.iter() {
        preimage.append(&Bytes::from_array(env, &gi.to_be_bytes()));
    }
    env.crypto().sha256(&preimage).into()
}

/// Recompute the gate leaf hash the way the contract does it.
fn compute_gate_leaf(
    env: &Env,
    table: &(BytesN<16>, BytesN<16>, BytesN<16>, BytesN<16>),
    gate_index: u32,
) -> BytesN<32> {
    let mut preimage = Bytes::new(env);
    for ct in [&table.0, &table.1, &table.2, &table.3] {
        preimage.append(&Bytes::from_array(env, &ct.to_array()));
    }
    preimage.append(&Bytes::from_array(env, &gate_index.to_be_bytes()));
    env.crypto().sha256(&preimage).into()
}

#[test]
fn integration_register_and_verify() {
    let env = Env::default();
    env.mock_all_auths();

    let contract_id = env.register_contract_wasm(None, WASM);
    let client = QuantumVerifierClient::new(&env, &contract_id);

    let admin = Address::generate(&env);
    client.init(&admin, &None, &0i128);

    let spec = CircuitSpec { lam: 128, msg_bits: 128, t: 2, sha256_circuit: 0 };

    // Honest material:
    //   r = 4 zero bytes; y_bits empty; s_claim = 0; r_dot_m_xor_s = 0.
    //   GL: gf2(r, y) ⊕ s_claim == r_dot_m_xor_s => 0 ⊕ 0 == 0 ✓
    let r = Bytes::from_array(&env, &[0u8; 4]);
    let r_dot_m_xor_s = 0u32;
    let mut non_reusable: Vec<u32> = Vec::new(&env);
    non_reusable.push_back(0u32);

    // Gate: k_l = k_r = k_o = all zero, gi = 0.
    // Yao: a = 0, b = 0, ct = table[0], pad = SHA-256(zero16||zero16||8_zero)[0..16],
    // xor = ct ^ pad. We set table[0] = pad so xor = zero16 = k_o. ✓
    let zero16 = BytesN::<16>::from_array(&env, &[0u8; 16]);
    let pad_value = quantum_verifier::crypto_helpers::pad(&env, &zero16, &zero16, 0u32);
    let table = (
        pad_value.clone(),
        zero16.clone(),
        zero16.clone(),
        zero16.clone(),
    );

    // Build the 2-leaf Merkle tree:
    //   root = SHA-256(leaf_G || leaf_H)   [left = gate, right = header]
    // The contract's verify_merkle with is_left=true computes
    // SHA-256(sibling || current); with is_left=false, SHA-256(current || sibling).
    // So if header is the right child of gate, then with is_left=true on header's
    // path, the preimage is leaf_G || leaf_H = puzzle_hash. ✓
    // And with is_left=false on gate's path, the preimage is leaf_G || leaf_H ✓.
    let leaf_h = compute_header_leaf(&env, &r, r_dot_m_xor_s, &non_reusable);
    let leaf_g = compute_gate_leaf(&env, &table, 0u32);
    let puzzle_hash = sha256_concat(&env, &leaf_g, &leaf_h);

    // For header (right child): sibling = leaf_G (left), is_left = true
    //   → preimage = leaf_G || header_leaf = puzzle_hash ✓
    let mut header_path: Vec<(BytesN<32>, bool)> = Vec::new(&env);
    header_path.push_back((leaf_g.clone(), true));
    // For gate (left child): sibling = leaf_H (right), is_left = false
    //   → preimage = gate_leaf || leaf_H = puzzle_hash ✓
    let mut gate_path: Vec<(BytesN<32>, bool)> = Vec::new(&env);
    gate_path.push_back((leaf_h.clone(), false));

    let spot_check = SpotCheckProof {
        gate_index: 0u32,
        k_l: zero16.clone(),
        k_r: zero16.clone(),
        k_o: zero16.clone(),
        table: table.clone(),
        merkle_path: gate_path,
    };
    let mut spot_checks: Vec<SpotCheckProof> = Vec::new(&env);
    spot_checks.push_back(spot_check);

    let y_bits: Vec<u32> = Vec::new(&env);

    let claim = Claim {
        header: ClaimHeader {
            r,
            r_dot_m_xor_s,
            non_reusable,
            merkle_path: header_path,
        },
        spot_checks,
        y_bits,
        s_claim: 0u32,
    };

    let circuit_hash = BytesN::from_array(&env, &[0u8; 32]);
    let pk_commitment = BytesN::from_array(&env, &[1u8; 32]);
    let puzzle_id = client.register_puzzle(&spec, &circuit_hash, &pk_commitment, &puzzle_hash, &0u32);
    println!("register_puzzle returned puzzle_id = {}", puzzle_id);
    assert_eq!(client.puzzle_count(), 1);

    let ok = client.submit_and_verify(&admin, &puzzle_id, &claim);
    println!("submit_and_verify returned {}", ok);
    println!("events: {:?}", env.events().all());
    assert!(ok, "honest claim should verify true");

    // Sanity: a bad s_claim should be rejected.
    let mut bad_claim = claim.clone();
    bad_claim.s_claim = 1u32;
    let bad = client.submit_and_verify(&admin, &puzzle_id, &bad_claim);
    println!("bad s_claim returned {}", bad);
    assert!(!bad, "wrong s_claim should reject");

    // ---- Real-TLP-style test: many non_reusable gates, gate_index != 0 ----
    let r2 = Bytes::from_array(&env, &[0u8; 16]);
    let mut nr2: Vec<u32> = Vec::new(&env);
    for i in 0..16u32 {
        nr2.push_back(i * 10);
    }
    let header_leaf2 = compute_header_leaf(&env, &r2, 0u32, &nr2);
    let gate0_idx = 30u32;  // pick one in the middle of nr2
    let table2 = (zero16.clone(), zero16.clone(), zero16.clone(), zero16.clone());
    let gate_leaf2 = compute_gate_leaf(&env, &table2, gate0_idx);
    let puzzle_hash2 = sha256_concat(&env, &gate_leaf2, &header_leaf2);

    // header is right child of gate
    let mut hp: Vec<(BytesN<32>, bool)> = Vec::new(&env);
    hp.push_back((gate_leaf2.clone(), true));
    // gate is left child of header
    let mut gp: Vec<(BytesN<32>, bool)> = Vec::new(&env);
    gp.push_back((header_leaf2.clone(), false));

    let mut sc2: Vec<SpotCheckProof> = Vec::new(&env);
    // expected_k_o = ct ^ pad(zero, zero, gate) = pad(zero, zero, gate),
    // so the solver's honest k_o is the pad itself.
    let k_o2 = quantum_verifier::crypto_helpers::pad(&env, &zero16, &zero16, gate0_idx);
    sc2.push_back(SpotCheckProof {
        gate_index: gate0_idx,
        k_l: zero16.clone(),
        k_r: zero16.clone(),
        k_o: k_o2,
        table: table2.clone(),
        merkle_path: gp,
    });

    let claim2 = Claim {
        header: ClaimHeader {
            r: r2,
            r_dot_m_xor_s: 0u32,
            non_reusable: nr2,
            merkle_path: hp,
        },
        spot_checks: sc2,
        y_bits: Vec::new(&env),
        s_claim: 0u32,
    };

    let pid2 = client.register_puzzle(
        &spec,
        &circuit_hash,
        &pk_commitment,
        &puzzle_hash2,
        &0u32,
    );
    println!("real-style puzzle_id = {}", pid2);
    let ok2 = client.submit_and_verify(&admin, &pid2, &claim2);
    println!("real-style submit_and_verify returned {}", ok2);
    assert!(ok2, "real-style honest claim should verify true");
}