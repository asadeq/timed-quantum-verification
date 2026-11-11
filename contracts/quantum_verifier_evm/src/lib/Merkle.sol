// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Cursor} from "./Cursor.sol";

/// @title Merkle — SHA-256 Merkle proof verification over the off-chain puzzle tree.
///
/// @notice The 49 KB puzzle body never touches the chain. It is Merkle-ized
///         off-chain into a single root (`puzzle_hash`), which is what
///         `registerPuzzle` stores. Each claim carries a path from the leaf it
///         needs up to that root, so the verifier can authenticate the header
///         material and the spot-checked gate tables without ever seeing the
///         puzzle body.
///
/// @dev Tree shape (built by `python/gen_fixtures.py::build_tree`):
///      ```
///      header leaf   = SHA-256( r || r_dot_m_xor_s_be32 || d || solver_be20 )
///                      d = SHA-256( y || s_claim || r ) — the registration-time
///                      commitment to the puzzle's embedded secret
///      gate leaf(gi) = SHA-256( table[gi]_4x16B || gi_be32 )
///      internal      = SHA-256( left || right )   (odd count: last pairs with itself)
///      ```
///      Path entries are `(sibling, is_left)` where `is_left == true` means the
///      sibling is the LEFT child, i.e. the current node is the right child.
library Merkle {
    using Cursor for Cursor.C;
    /// @notice Fold `leaf` up a path read from `c` and compare against `root`.
    /// @dev Consumes `u32 count` followed by `count` × (bytes32 sibling, u8 isLeft)
    ///      from the cursor. Reading straight from calldata avoids allocating a
    ///      `bytes32[]` per proof, which for K=8 would be 8 separate arrays.
    function verifyFromCursor(Cursor.C memory c, bytes32 leaf, bytes32 root)
        internal
        pure
        returns (bool)
    {
        uint32 n = c.u32();
        bytes32 cur = leaf;
        for (uint32 i = 0; i < n; ++i) {
            bytes32 sibling = c.b32();
            bool isLeft = c.bool1();
            cur = isLeft
                ? sha256(abi.encodePacked(sibling, cur))
                : sha256(abi.encodePacked(cur, sibling));
        }
        return cur == root;
    }

    /// @notice Fold `leaf` up an in-memory path and compare against `root`.
    /// @dev Used by tests and by the off-chain reference implementation.
    function verify(bytes32 leaf, bytes32[] memory siblings, bool[] memory isLeft, bytes32 root)
        internal
        pure
        returns (bool)
    {
        require(siblings.length == isLeft.length, "Merkle: length mismatch");
        bytes32 cur = leaf;
        for (uint256 i = 0; i < siblings.length; ++i) {
            cur = isLeft[i]
                ? sha256(abi.encodePacked(siblings[i], cur))
                : sha256(abi.encodePacked(cur, siblings[i]));
        }
        return cur == root;
    }

    /// @notice Hash an internal node from its two children.
    function node(bytes32 left, bytes32 right) internal pure returns (bytes32) {
        return sha256(abi.encodePacked(left, right));
    }
}
