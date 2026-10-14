// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Cursor} from "./Cursor.sol";

/// @title ClaimCodec — decode the packed claim wire format.
///
/// @notice Format (all integers big-endian; see `docs/WIRE_FORMAT_EVM.md`):
///
/// ```
/// u32            r_len
/// bytes          r                      (Goldreich-Levin mask)
/// u8             r_dot_m_xor_s
/// u32            bitmap_len
/// bytes          bitmap                 (bit gi set => gate gi is non-reusable)
/// u32            header_path_count
/// (bytes32,u8)[] header_path            (sibling, is_left)
/// u32            spot_checks_count      (K)
/// SpotCheck[] {
///     u32            gate_index
///     bytes16        k_l
///     bytes16        k_r
///     bytes16        k_o
///     bytes16[4]     table              (row-major (a,b)=(00,01,10,11))
///     u32            path_count
///     (bytes32,u8)[] path
/// }
/// u32            y_len
/// bytes          y                      (circuit output bits, LSB-first)
/// u8             s_claim
/// ```
///
/// @dev Two deliberate departures from the Soroban wire format in `SPEC.md`:
///
///      1. **The non-reusable gate list is a bitmap, not a `u32[]`.** For
///         `lam = msg_bits = 128` there are 640 non-reusable gates with a max
///         index of 895, so the list costs 2,564 bytes — 38% of the whole claim.
///         A 112-byte bitmap replaces it, and membership becomes an O(1) bit
///         test instead of the O(K x N) linear scan the Rust version does.
///         At 40 gas/byte that is ~99,000 gas saved per verification.
///
///      2. **`r_dot_m_xor_s` and `s_claim` are single bytes, not u32.** They are
///         bits; the extra 3 bytes each were pure padding.
///
///      Consequence: the EVM `puzzle_hash` differs from the Soroban one, because
///      the header leaf commits to the bitmap rather than the list. That is fine
///      for the dual-chain story — `registerPuzzle` takes the hash as a
///      parameter, so you compute each chain's hash off-chain and register it on
///      that chain. The claim bytes differ anyway (`scval` vs packed calldata).
library ClaimCodec {
    using Cursor for Cursor.C;

    /// @dev Caps on caller-controlled lengths. Without these a malicious claim
    ///      could force unbounded memory allocation before any check runs.
    uint256 internal constant MAX_R_LEN = 64;
    // Bitmap length = ceil(max_gate_index / 8), and max gate index grows with
    // the circuit size (T=1 -> 112 B, T=100 -> 1,696 B). 4096 B supports gate
    // indices up to 32,767, i.e. T well past 200. This is a sanity cap against
    // absurd claims, not a protocol limit — the real limit is calldata pricing.
    uint256 internal constant MAX_BITMAP_LEN = 4096;
    uint256 internal constant MAX_Y_LEN = 64;
    uint256 internal constant MAX_K = 64;
    uint256 internal constant MAX_PATH_DEPTH = 64;

    error TooLarge(string field, uint256 value, uint256 max);
    error LengthMismatch(string field, uint256 a, uint256 b);

    struct SpotCheckView {
        uint32 gateIndex;
        bytes16 kL;
        bytes16 kR;
        bytes16 kO;
        /// @dev Calldata offset of the 64-byte table (4 x bytes16, row-major).
        uint256 tableOff;
        /// @dev Calldata offset of the path's u32 count.
        uint256 pathOff;
    }

    struct ClaimView {
        uint256 rOff;
        uint32 rLen;
        uint8 rDotMXorS;
        uint256 bitmapOff;
        uint32 bitmapLen;
        /// @dev Calldata offset of the header path's u32 count.
        uint256 headerPathOff;
        SpotCheckView[] spotChecks;
        uint256 yOff;
        uint32 yLen;
        uint8 sClaim;
        /// @dev End of the claim region, so sub-cursors can bounds-check.
        uint256 end;
    }

    /// @notice Decode a claim, validating every length and consuming it exactly.
    function decode(bytes calldata data) internal pure returns (ClaimView memory v) {
        Cursor.C memory c = Cursor.init(data);
        v.end = c.end;

        v.rLen = c.u32();
        _cap("r", v.rLen, MAX_R_LEN);
        v.rOff = c.skip(v.rLen);

        v.rDotMXorS = c.u8();
        if (v.rDotMXorS > 1) revert TooLarge("r_dot_m_xor_s", v.rDotMXorS, 1);

        v.bitmapLen = c.u32();
        _cap("bitmap", v.bitmapLen, MAX_BITMAP_LEN);
        v.bitmapOff = c.skip(v.bitmapLen);

        v.headerPathOff = c.off;
        _skipPath(c);

        uint32 k = c.u32();
        _cap("K", k, MAX_K);
        v.spotChecks = new SpotCheckView[](k);
        for (uint32 i = 0; i < k; ++i) {
            SpotCheckView memory sc = v.spotChecks[i];
            sc.gateIndex = c.u32();
            sc.kL = c.key16();
            sc.kR = c.key16();
            sc.kO = c.key16();
            sc.tableOff = c.skip(64);
            sc.pathOff = c.off;
            _skipPath(c);
        }

        v.yLen = c.u32();
        _cap("y", v.yLen, MAX_Y_LEN);
        v.yOff = c.skip(v.yLen);

        v.sClaim = c.u8();
        if (v.sClaim > 1) revert TooLarge("s_claim", v.sClaim, 1);

        c.expectDone();

        // The GL check is a byte-wise inner product, so the two operands must be
        // the same length. The Rust original silently truncated to the shorter
        // one via `min(a.len(), b.len())`, which would let a solver choose how
        // much of `r` gets checked.
        if (v.rLen != v.yLen) revert LengthMismatch("r/y", v.rLen, v.yLen);
    }

    /// @notice Test whether `gateIndex` is marked non-reusable in the bitmap.
    /// @dev O(1). Replaces the Rust `non_reusable.iter().position(...)` scan,
    ///      which was O(K x N) — ~50,000 gas on the EVM, comparable to the
    ///      entire calldata cost.
    function isNonReusable(ClaimView memory v, uint32 gateIndex)
        internal
        pure
        returns (bool)
    {
        uint256 byteIdx = uint256(gateIndex) >> 3;
        if (byteIdx >= v.bitmapLen) return false;
        uint256 off = v.bitmapOff + byteIdx;
        uint8 b;
        assembly ("memory-safe") {
            b := shr(248, calldataload(off))
        }
        return (b >> (gateIndex & 7)) & 1 == 1;
    }

    /// @notice Copy a calldata region into a fresh `bytes`.
    function slice(uint256 off, uint256 len) internal pure returns (bytes memory out) {
        out = new bytes(len);
        assembly ("memory-safe") {
            calldatacopy(add(out, 32), off, len)
        }
    }

    function _skipPath(Cursor.C memory c) private pure {
        uint32 n = c.u32();
        _cap("path", n, MAX_PATH_DEPTH);
        c.skip(uint256(n) * 33);
    }

    function _cap(string memory field, uint256 value, uint256 max) private pure {
        if (value > max) revert TooLarge(field, value, max);
    }
}
