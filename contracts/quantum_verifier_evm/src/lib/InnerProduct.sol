// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title InnerProduct — the Goldreich-Levin linear post-processing check.
///
/// @notice The final on-chain check is
///         `gf2(r, y) XOR s_claim == r_dot_m_xor_s`, i.e. one GF(2) inner
///         product and one XOR. No hashing.
///
/// @dev The Rust original expands `r` into a `Vec<u32>` of bits
///      (`bytes_to_bits_u32`, LSB-first) and runs `gf2_inner_product` against
///      `y_bits`. That is equivalent to a **byte-wise** computation: the parity
///      of `bit_i(r) AND bit_i(y)` summed over a byte equals the parity of
///      `r_byte AND y_byte`. So the whole check collapses to
///
///      ```
///      acc = XOR over i of (r[i] & y[i]);   result = parity8(acc)
///      ```
///
///      which is O(n) XORs plus one parity, with no bit expansion and no
///      allocation. Measured `r` and `y` are both 16 bytes for
///      `lam = msg_bits = 128`.
library InnerProduct {
    /// @notice GF(2) inner product of two equal-length byte strings.
    /// @dev Reverts on a length mismatch rather than silently truncating to the
    ///      shorter input the way the Rust `min(a.len(), b.len())` does. A
    ///      mismatch means the claim is malformed, and silently accepting it
    ///      would let a solver choose which prefix of `r` is checked.
    function gf2(bytes calldata a, bytes calldata b) internal pure returns (uint8) {
        require(a.length == b.length, "InnerProduct: length mismatch");
        uint8 acc;
        for (uint256 i = 0; i < a.length; ++i) {
            acc ^= uint8(a[i] & b[i]);
        }
        return parity8(acc);
    }

    /// @notice Memory variant used by tests and by callers holding bytes memory.
    function gf2Memory(bytes memory a, bytes memory b) internal pure returns (uint8) {
        require(a.length == b.length, "InnerProduct: length mismatch");
        uint8 acc;
        for (uint256 i = 0; i < a.length; ++i) {
            acc ^= uint8(a[i] & b[i]);
        }
        return parity8(acc);
    }

    /// @notice GF(2) inner product over two calldata regions.
    function gf2Calldata(uint256 aOff, uint256 bOff, uint256 n) internal pure returns (uint8) {
        uint8 acc;
        for (uint256 i = 0; i < n; ++i) {
            uint8 x;
            uint8 y;
            assembly ("memory-safe") {
                x := shr(248, calldataload(add(aOff, i)))
                y := shr(248, calldataload(add(bOff, i)))
            }
            acc ^= x & y;
        }
        return parity8(acc);
    }

    /// @notice Parity (popcount mod 2) of a byte.
    function parity8(uint8 x) internal pure returns (uint8) {
        x ^= x >> 4;
        x ^= x >> 2;
        x ^= x >> 1;
        return x & 1;
    }

    /// @notice Parity of a 256-bit word.
    function parity256(uint256 x) internal pure returns (uint256) {
        x ^= x >> 128;
        x ^= x >> 64;
        x ^= x >> 32;
        x ^= x >> 16;
        x ^= x >> 8;
        x ^= x >> 4;
        x ^= x >> 2;
        x ^= x >> 1;
        return x & 1;
    }
}
