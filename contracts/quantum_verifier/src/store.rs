//! Instance storage helpers for the puzzle registry.

use soroban_sdk::{panic_with_error, Address, Env};

use crate::types::{DataKey, PuzzleMeta};
use crate::verifier::VerifierError;

/// Read the admin address. Surfaces a `VerifierError::AdminNotSet` SCError if
/// `init` hasn't been called yet. Using `panic_with_error!` (instead of
/// `expect`) ensures the diagnostic event carries the error code instead of a
/// stripped panic message.
pub fn read_admin(env: &Env) -> Address {
    env.storage()
        .instance()
        .get(&DataKey::Admin)
        .unwrap_or_else(|| panic_with_error!(&env, VerifierError::AdminNotSet))
}

/// Write the admin address.
pub fn write_admin(env: &Env, admin: &Address) {
    env.storage().instance().set(&DataKey::Admin, admin);
}

/// Read the global per-verify fee. Defaults to 0.
pub fn read_fee_per_verify(env: &Env) -> i128 {
    env.storage()
        .instance()
        .get(&DataKey::FeePerVerify)
        .unwrap_or(0)
}

/// Write the global per-verify fee.
pub fn write_fee_per_verify(env: &Env, fee: i128) {
    env.storage().instance().set(&DataKey::FeePerVerify, &fee);
}

/// Read the payment token address. Returns None if not configured (free mode).
pub fn read_payment_token(env: &Env) -> Option<Address> {
    env.storage().instance().get(&DataKey::PaymentToken)
}

/// Write the payment token address.
pub fn write_payment_token(env: &Env, token: &Address) {
    env.storage().instance().set(&DataKey::PaymentToken, token);
}

/// Clear the payment token (switch to free mode).
pub fn clear_payment_token(env: &Env) {
    env.storage().instance().remove(&DataKey::PaymentToken);
}

/// Read the total fees collected. Defaults to 0.
pub fn read_total_collected(env: &Env) -> i128 {
    env.storage()
        .instance()
        .get(&DataKey::TotalCollected)
        .unwrap_or(0)
}

/// Add `amount` to the total collected.
pub fn add_to_total_collected(env: &Env, amount: i128) {
    let current = read_total_collected(env);
    env.storage()
        .instance()
        .set(&DataKey::TotalCollected, &(current + amount));
}

/// Read the current puzzle count. Defaults to 0.
pub fn read_puzzle_count(env: &Env) -> u32 {
    env.storage()
        .instance()
        .get(&DataKey::PuzzleCount)
        .unwrap_or(0)
}

/// Increment and return the new puzzle count.
pub fn increment_puzzle_count(env: &Env) -> u32 {
    let n = read_puzzle_count(env) + 1;
    env.storage().instance().set(&DataKey::PuzzleCount, &n);
    n
}

/// Read a puzzle's metadata. Returns None if not registered.
pub fn read_puzzle_meta(env: &Env, puzzle_id: u32) -> Option<PuzzleMeta> {
    env.storage().instance().get(&DataKey::Meta(puzzle_id))
}

/// Write a puzzle's metadata.
pub fn write_puzzle_meta(env: &Env, puzzle_id: u32, meta: &PuzzleMeta) {
    env.storage().instance().set(&DataKey::Meta(puzzle_id), meta);
}
