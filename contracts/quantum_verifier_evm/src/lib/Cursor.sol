// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title Cursor — a bounds-checked reader over `bytes calldata`.
///
/// @notice The claim is submitted in the **packed** wire format (see
///         `docs/WIRE_FORMAT_EVM.md`), not ABI-encoded. ABI-encoding a struct
///         with nested dynamic arrays adds an offset word and a length word to
///         every field plus 32-byte padding, roughly tripling the calldata —
///         and on the EVM calldata is ~77% of the verification bill.
///
/// @dev Every read is bounds-checked. This matters more than it looks:
///      `calldataload` past the end of calldata silently returns zero rather
///      than reverting, so an unchecked decoder would accept truncated claims
///      and treat the missing bytes as zeros. Solidity 0.8's overflow checks
///      do not apply inside `assembly`, so the checks are explicit here.
library Cursor {
    /// @dev A read ran past the end of the claim.
    error Truncated(uint256 offset, uint256 need, uint256 end);
    /// @dev Bytes remained after the claim was fully decoded.
    error TrailingBytes(uint256 offset, uint256 end);

    struct C {
        uint256 off;
        uint256 end;
    }

    /// @notice Open a cursor over a calldata region.
    function init(uint256 off, uint256 len) internal pure returns (C memory c) {
        c.off = off;
        c.end = off + len;
    }

    /// @notice Open a cursor over a `bytes calldata` argument.
    /// @dev `data.offset` / `data.length` are Yul-readable as plain values for
    ///      calldata arrays; do not mload them (they are calldata offsets, not
    ///      memory pointers).
    function init(bytes calldata data) internal pure returns (C memory c) {
        uint256 off;
        uint256 len;
        assembly ("memory-safe") {
            off := data.offset
            len := data.length
        }
        c.off = off;
        c.end = off + len;
    }

    /// @notice Read one byte.
    function u8(C memory c) internal pure returns (uint8 v) {
        _need(c, 1);
        assembly ("memory-safe") {
            v := shr(248, calldataload(mload(c)))
        }
        c.off += 1;
    }

    /// @notice Read a big-endian u32.
    function u32(C memory c) internal pure returns (uint32 v) {
        _need(c, 4);
        assembly ("memory-safe") {
            v := shr(224, calldataload(mload(c)))
        }
        c.off += 4;
    }

    /// @notice Read a 32-byte word.
    function b32(C memory c) internal pure returns (bytes32 v) {
        _need(c, 32);
        assembly ("memory-safe") {
            v := calldataload(mload(c))
        }
        c.off += 32;
    }

    /// @notice Read a 16-byte Yao key.
    /// @dev Solidity value types shorter than 32 bytes are LEFT-aligned in
    ///      their stack slot, and `calldataload` returns the 32 bytes starting
    ///      at the offset with the first byte in the high position — so loading
    ///      the full word directly yields the key, correctly aligned. Do NOT
    ///      `shr(128)` here: that would right-align the value into the wrong
    ///      half and decode every key as zero (this exact bug shipped and was
    ///      caught by the golden-vector integration test).
    function key16(C memory c) internal pure returns (bytes16 v) {
        _need(c, 16);
        assembly ("memory-safe") {
            v := calldataload(mload(c))
        }
        c.off += 16;
    }

    /// @notice Read a boolean encoded as a single 0/1 byte.
    /// @dev Rejects values > 1. Without this, `2` and `0` would both decode to
    ///      `false`, so two distinct claim byte strings could produce the same
    ///      verdict — a malleability hole in a contract that emits a claim hash.
    function bool1(C memory c) internal pure returns (bool v) {
        uint8 b = u8(c);
        if (b > 1) revert Truncated(c.off - 1, 1, c.end);
        v = (b == 1);
    }

    /// @notice Advance past `n` bytes and return the offset of the skipped region.
    /// @dev Used for variable-length blobs (`r`, `y`) that are
    ///      hashed or scanned in place rather than copied into memory.
    function skip(C memory c, uint256 n) internal pure returns (uint256 off) {
        _need(c, n);
        off = c.off;
        c.off += n;
    }

    /// @notice True iff the cursor has consumed exactly the whole region.
    function done(C memory c) internal pure returns (bool) {
        return c.off == c.end;
    }

    /// @notice Revert unless the cursor is fully consumed.
    function expectDone(C memory c) internal pure {
        if (c.off != c.end) revert TrailingBytes(c.off, c.end);
    }

    function _need(C memory c, uint256 n) private pure {
        if (c.off + n > c.end) revert Truncated(c.off, n, c.end);
    }
}
