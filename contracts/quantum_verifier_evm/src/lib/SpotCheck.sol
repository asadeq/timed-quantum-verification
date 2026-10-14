// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title SpotCheck — the TLP gate-decryption check.
///
/// @notice The heart of the design. The TLP's time-lock is a one-time cost paid
///         by the solver: once they have done the T sequential SHA-256 steps and
///         produced a candidate `y`, the verifier only needs to confirm they
///         really did the work. For each of K randomly chosen non-reusable gates
///         the solver supplies the gate's 4 ciphertexts and the Yao keys they
///         used, and the contract checks:
///
///         ```
///         a = select_bit(k_l)                  # point-and-permute row
///         b = select_bit(k_r)
///         ct = table[a*2 + b]                  # the garbled ciphertext
///         k_o == ct XOR pad(k_l, k_r, gi)
///         ```
///
///         The keys are deterministic given an honest execution: once the solver
///         has `K_unlock` and the boundary keys, every gate's keys follow from
///         the puzzle. A solver who skipped the T sequential steps cannot produce
///         consistent keys for any K >= 1. With K = 8 the cheating probability is
///         2^-8; with K = 16 it is 1.5e-5.
///
/// @dev This is a 1:1 port of `contracts/quantum_verifier/src/spot_check.rs` and
///      `crypto_helpers.rs`. The Rust original computed `pad()` twice and
///      repeated the comparison three times (a copy-paste artifact); that is not
///      reproduced here.
library SpotCheck {
    /// @notice Per-(gate, row) one-time pad derived from the two parent keys.
    /// @dev `SHA-256(k_left || k_right || gate_index_be64)[:16]`.
    ///      Note the 8-byte big-endian index: the Rust original zero-extends a
    ///      u32 into a u64, so the preimage is 16 + 16 + 8 = 40 bytes.
    function pad(bytes16 kLeft, bytes16 kRight, uint32 gateIndex)
        internal
        pure
        returns (bytes16)
    {
        bytes32 digest = sha256(abi.encodePacked(kLeft, kRight, uint64(gateIndex)));
        // First 16 bytes of the digest, matching `digest[..16]` in Rust.
        return bytes16(digest);
    }

    /// @notice The point-and-permute select bit encoded in the key's first byte.
    function selectBit(bytes16 key) internal pure returns (uint8) {
        return uint8(key[0]) & 1;
    }

    /// @notice Verify one gate's decryption.
    /// @param kL Left-parent Yao key the solver used.
    /// @param kR Right-parent Yao key the solver used.
    /// @param kO Output-wire Yao key the solver claims to have recovered.
    /// @param table The gate's 4 garbled ciphertexts, row-major
    ///        `(a,b) = (0,0),(0,1),(1,0),(1,1)`.
    /// @param gateIndex The gate's index in the circuit (binds the pad).
    function verifyOne(
        bytes16 kL,
        bytes16 kR,
        bytes16 kO,
        bytes16[4] memory table,
        uint32 gateIndex
    ) internal pure returns (bool) {
        uint8 a = selectBit(kL);
        uint8 b = selectBit(kR);
        bytes16 ct = table[a * 2 + b];
        return (ct ^ pad(kL, kR, gateIndex)) == kO;
    }

    /// @notice Verify one gate's decryption, reading the table from calldata.
    /// @dev Same check as `verifyOne` but avoids materialising a `bytes16[4]`
    ///      when the caller already holds the table's calldata offset.
    ///      NB: no `shr(128)` when reading `ct` — `bytes16` is left-aligned in
    ///      its stack slot, and `calldataload` puts the first byte high, so the
    ///      full-word load is already correctly aligned.
    function verifyOneCalldata(
        bytes16 kL,
        bytes16 kR,
        bytes16 kO,
        uint256 tableOff,
        uint32 gateIndex
    ) internal pure returns (bool) {
        uint8 a = selectBit(kL);
        uint8 b = selectBit(kR);
        uint256 idx = (uint256(a) * 2 + uint256(b)) * 16;
        bytes16 ct;
        assembly ("memory-safe") {
            ct := calldataload(add(tableOff, idx))
        }
        return (ct ^ pad(kL, kR, gateIndex)) == kO;
    }
}
