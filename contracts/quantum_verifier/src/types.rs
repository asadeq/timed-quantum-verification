//! Contract types matching the canonical wire format in [SPEC.md](../../SPEC.md).
//!
//! All types use `#[contracttype]` so they can cross the WASM boundary.

use soroban_sdk::{contracttype, Bytes, BytesN, Vec};

// ---------------------------------------------------------------------------
// CircuitSpec — immutable, set at PSetup
// ---------------------------------------------------------------------------

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitSpec {
    pub lam: u32,
    pub msg_bits: u32,
    pub t: u32,
    pub sha256_circuit: u32, // 0 = xor_mixing, 1 = sha256
}

// ---------------------------------------------------------------------------
// PuzzleMeta — public per-puzzle metadata
// ---------------------------------------------------------------------------

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PuzzleMeta {
    pub circuit_hash: BytesN<32>,
    /// Commitment to the off-chain garbling setup.
    pub pk_commitment: BytesN<32>,
    /// SHA-256 of the canonical serialization of the off-chain Puzzle body.
    /// The puzzle body itself stays off-chain — it's far too large for
    /// Soroban's per-tx write footprint. Instead, the solver submits a
    /// Merkle proof inside `Claim` that the spot-checked gates come from
    /// the puzzle with this hash.
    pub puzzle_hash: BytesN<32>,
    pub fee: u32,
}

// ---------------------------------------------------------------------------
// Puzzle — per-instance, off-chain PGen output (NEVER stored on-chain)
// ---------------------------------------------------------------------------
//
// `Puzzle` exists in the wire format (the Python serializer produces it)
// but the contract does not store it. The relevant fields are submitted
// inside `Claim` along with a Merkle proof binding them to `puzzle_hash`.

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Puzzle {
    pub r: Bytes,
    pub r_dot_m_xor_s: u32,
    /// Sorted list of non-reusable gate indices.
    pub non_reusable: Vec<u32>,
    /// 4 ciphertexts per gate, flattened row-major:
    /// tables[gi][0] = ct for (a,b) = (0,0), [1] = (0,1), [2] = (1,0), [3] = (1,1).
    pub tables_flat: Vec<BytesN<16>>,
    /// Sealed boundary keys, sorted by wire_id. (Off-chain only.)
    pub sealed_boundary: Vec<(u32, BytesN<16>)>,
    /// Output permutation bits, sorted by wire_id. (Off-chain only.)
    pub out_perm: Vec<(u32, u32)>,
}

// ---------------------------------------------------------------------------
// SpotCheckProof — one gate's worth of spot-check material in a Claim
// ---------------------------------------------------------------------------

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SpotCheckProof {
    /// Index into `ClaimHeader.non_reusable` (sorted ascending) of the gate
    /// being checked.
    pub gate_index: u32,
    /// Yao keys for this gate's left/right input wires and output wire.
    pub k_l: BytesN<16>,
    pub k_r: BytesN<16>,
    pub k_o: BytesN<16>,
    /// The 4 ciphertexts of the gate's garbled truth table, row-major
    /// (a, b) ∈ {(0,0),(0,1),(1,0),(1,1)}.
    pub table: (BytesN<16>, BytesN<16>, BytesN<16>, BytesN<16>),
    /// Merkle proof from `SHA-256(table_bytes || gate_index_be32)` up to
    /// the registered `puzzle_hash`. Bounds the solver to a real table
    /// from the registered puzzle.
    pub merkle_path: Vec<(BytesN<32>, bool)>,
}

// ---------------------------------------------------------------------------
// ClaimHeader — r + r_dot_m_xor_s + non_reusable, with Merkle binding
// ---------------------------------------------------------------------------

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ClaimHeader {
    /// Goldreich-Levin mask.
    pub r: Bytes,
    /// r·m ⊕ s commitment (0 or 1).
    pub r_dot_m_xor_s: u32,
    /// Sorted non-reusable gate indices.
    pub non_reusable: Vec<u32>,
    /// Merkle proof from `SHA-256(r || r_dot_m_xor_s || non_reusable_bytes)`
    /// up to the registered `puzzle_hash`.
    pub merkle_path: Vec<(BytesN<32>, bool)>,
}

// ---------------------------------------------------------------------------
// Claim — per-call, the solver's submission. Puzzle body never touches
// the chain — only this Claim and the registered `puzzle_hash` do.
// ---------------------------------------------------------------------------

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Claim {
    pub header: ClaimHeader,
    /// Per-gate spot-check material. Each entry is bound to `puzzle_hash`
    /// via its own Merkle proof.
    pub spot_checks: Vec<SpotCheckProof>,
    /// LSB-first circuit-output bits.
    pub y_bits: Vec<u32>, // each entry is 0 or 1
    pub s_claim: u32,     // 0 or 1
}

// ---------------------------------------------------------------------------
// Storage keys
// ---------------------------------------------------------------------------

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DataKey {
    /// Address of the admin (only address allowed to register puzzles).
    Admin,
    /// Total number of registered puzzles.
    PuzzleCount,
    /// puzzle_id → PuzzleMeta
    Meta(u32),
    /// Address of the token used for payment (SAC).
    PaymentToken,
    /// Global fee per verification call.
    FeePerVerify,
    /// Total fees accumulated in the contract.
    TotalCollected,
}

// ---------------------------------------------------------------------------
// Events
// ---------------------------------------------------------------------------

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PuzzleRegistered {
    pub puzzle_id: u32,
    pub fee: u32,
}

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Verified {
    pub puzzle_id: u32,
    pub solver: soroban_sdk::Address,
    pub claim_hash: BytesN<32>,
    pub s: u32,
}

#[contracttype]
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Rejected {
    pub puzzle_id: u32,
    pub solver: soroban_sdk::Address,
    pub reason: u32,
}