// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title ReentrancyGuard — minimal single-slot guard.
///
/// @dev `submitAndVerify` makes an external call (the fee transfer) before it
///      does any verification work, and `withdraw` sends value out. Both are
///      guarded. The guard is written inline rather than pulled from
///      OpenZeppelin so the verifier stays dependency-free.
abstract contract ReentrancyGuard {
    uint256 private constant NOT_ENTERED = 1;
    uint256 private constant ENTERED = 2;

    uint256 private _status = NOT_ENTERED;

    error ReentrantCall();

    modifier nonReentrant() {
        if (_status == ENTERED) revert ReentrantCall();
        _status = ENTERED;
        _;
        _status = NOT_ENTERED;
    }
}
