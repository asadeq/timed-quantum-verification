// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Cursor} from "./lib/Cursor.sol";
import {Merkle} from "./lib/Merkle.sol";
import {SpotCheck} from "./lib/SpotCheck.sol";
import {InnerProduct} from "./lib/InnerProduct.sol";
import {ClaimCodec} from "./lib/ClaimCodec.sol";
import {SafeERC20} from "./lib/SafeERC20.sol";
import {IERC20} from "./interfaces/IERC20.sol";
import {ReentrancyGuard} from "./utils/ReentrancyGuard.sol";

/// @title QuantumVerifier — on-chain claim verifier for
///        Quantum-Verification-as-a-Service.
///
/// @notice The contract does **not** re-solve the TLP. The time-lock is a
///         one-time cost paid by the solver: once they have done the T
///         sequential SHA-256 steps and produced a candidate `y`, the verifier
///         only needs to (a) verify the quantum run via a Merkle proof and
///         (b) spot-check a handful of the solver's TLP gate-decryptions to
///         confirm they really did the work. The on-chain work is a constant
///         amount of SHA-256 over a few KB of proof bytes — independent of T.
///
///         The 49 KB puzzle body never touches the chain. `registerPuzzle`
///         stores only its Merkle root (`puzzleHash`) — plus an optional
///         escrowed bounty — and each claim carries paths binding the header
///         material and the spot-checked gate tables back to that root. A
///         successful claim atomically releases the bounty to the submitting
///         solver (verify-then-settle in one transaction). The header leaf
///         commits to the submitter's address, so a valid claim is only valid
///         from the account it was built for and cannot be front-run or
///         replayed by a bystander.
///
/// @dev Port of `contracts/quantum_verifier` (Soroban/Rust). The four rejection
///      reasons are preserved exactly so the two implementations can be
///      differential-tested against the same fixtures. Reasons 5+ and the
///      escrow flow are EVM-only extensions:
///
///      | reason | check |
///      |---|---|
///      | 0 | puzzle not registered |
///      | 1 | header Merkle path does not resolve to `puzzleHash` (includes wrong solver) |
///      | 2 | a spot-check's Merkle path does not resolve to `puzzleHash` |
///      | 3 | Yao spot-check failed (or gate not marked non-reusable) |
///      | 4 | Goldreich-Levin check failed |
///      | 5 | bounty already claimed (EVM only) |
contract QuantumVerifier is ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct PuzzleMeta {
        bytes32 circuitHash;
        bytes32 pkCommitment;
        bytes32 puzzleHash;
        uint32 fee;
        /// @dev Escrowed reward paid to the first honest solver. `0` means the
        ///      puzzle is verify-only (any number of successful verifications).
        uint96 bounty;
        /// @dev Solver that already claimed the bounty; `address(0)` while
        ///      unclaimed. Packs with `bounty` into one slot (96 + 160 bits).
        address claimedBy;
    }

    /// @dev Sanity cap on a per-puzzle fee, to catch unit mistakes (stroops vs
    ///      wei vs token decimals) before they reach users.
    uint32 public constant MAX_PUZZLE_FEE = 1_000_000_000;

    /// @notice Address allowed to register puzzles and withdraw fees.
    address public immutable admin;

    /// @notice Token used for payment. `address(0)` means native ETH.
    address public immutable paymentToken;

    /// @notice Global per-verification fee. `0` disables payment entirely
    ///         ("free mode"), which is what the testnet demo runs in.
    uint256 public feePerVerify;

    /// @notice Fees accumulated and not yet withdrawn.
    uint256 public totalCollected;

    /// @notice Number of registered puzzles. Ids start at 1, matching the
    ///         Soroban contract's `increment_puzzle_count`.
    uint32 public puzzleCount;

    mapping(uint32 => PuzzleMeta) public puzzleMeta;

    event PuzzleRegistered(uint32 indexed puzzleId, uint32 fee, uint96 bounty);
    event Verified(uint32 indexed puzzleId, address indexed solver, bytes32 claimHash, uint8 s);
    event Rejected(uint32 indexed puzzleId, address indexed solver, uint8 reason);
    event BountyPaid(uint32 indexed puzzleId, address indexed solver, uint96 amount);
    event BountyReclaimed(uint32 indexed puzzleId, address indexed to, uint96 amount);
    event FeeUpdated(uint256 oldFee, uint256 newFee);
    event Withdrawn(address indexed to, uint256 amount);

    error NotAdmin();
    error WrongFee(uint256 expected, uint256 got);
    error UnexpectedValue();
    error TransferFailed();
    error FeeTooHigh(uint32 fee, uint32 max);
    error NothingToReclaim();

    /// @param admin_ Address allowed to register puzzles and withdraw.
    /// @param paymentToken_ ERC-20 to charge in, or `address(0)` for native ETH.
    /// @param feePerVerify_ Initial fee; `0` for free mode.
    constructor(address admin_, address paymentToken_, uint256 feePerVerify_) {
        admin = admin_;
        paymentToken = paymentToken_;
        feePerVerify = feePerVerify_;
    }

    // -----------------------------------------------------------------------
    // Admin
    // -----------------------------------------------------------------------

    /// @notice Register a puzzle by its commitment. Admin only.
    /// @dev Only the Merkle root is stored. The puzzle body stays off-chain.
    ///      A non-zero `bounty` is escrowed here (msg.value for native ETH,
    ///      `transferFrom` for ERC-20) and paid atomically to the first solver
    ///      whose claim verifies. The bounty makes the claim's header leaf
    ///      economically meaningful: without a reward, front-running a claim
    ///      is harmless, with one it must be impossible — which is why the
    ///      leaf also binds `msg.sender`.
    /// @return puzzleId The new puzzle's id (starts at 1).
    function registerPuzzle(
        bytes32 circuitHash,
        bytes32 pkCommitment,
        bytes32 puzzleHash,
        uint32 fee,
        uint96 bounty
    ) external payable returns (uint32 puzzleId) {
        if (msg.sender != admin) revert NotAdmin();
        if (fee > MAX_PUZZLE_FEE) revert FeeTooHigh(fee, MAX_PUZZLE_FEE);

        if (bounty != 0) {
            if (paymentToken == address(0)) {
                if (msg.value != bounty) revert WrongFee(bounty, msg.value);
            } else {
                if (msg.value != 0) revert UnexpectedValue();
                IERC20(paymentToken).safeTransferFrom(msg.sender, address(this), bounty);
            }
        } else if (msg.value != 0) {
            revert UnexpectedValue();
        }

        puzzleId = ++puzzleCount;
        puzzleMeta[puzzleId] = PuzzleMeta({
            circuitHash: circuitHash,
            pkCommitment: pkCommitment,
            puzzleHash: puzzleHash,
            fee: fee,
            bounty: bounty,
            claimedBy: address(0)
        });

        emit PuzzleRegistered(puzzleId, fee, bounty);
    }

    /// @notice Update the global per-verification fee. Admin only.
    function setFeePerVerify(uint256 newFee) external {
        if (msg.sender != admin) revert NotAdmin();
        uint256 old = feePerVerify;
        feePerVerify = newFee;
        emit FeeUpdated(old, newFee);
    }

    /// @notice Sweep accumulated fees. Admin only.
    /// @dev Checks-effects-interactions: the balance is zeroed before the
    ///      external call, and the function is `nonReentrant`.
    function withdraw(address to) external nonReentrant {
        if (msg.sender != admin) revert NotAdmin();

        uint256 amount = totalCollected;
        totalCollected = 0;
        if (amount == 0) return;

        if (paymentToken == address(0)) {
            (bool ok,) = to.call{value: amount}("");
            if (!ok) revert TransferFailed();
        } else {
            IERC20(paymentToken).safeTransfer(to, amount);
        }

        emit Withdrawn(to, amount);
    }

    /// @notice Return an unclaimed bounty to the admin.
    /// @dev For puzzles nobody ever solves honestly; claimed bounties are gone
    ///      for good (they were paid out), and there is deliberately no
    ///      deadline — a puzzle stays solvable as long as the admin leaves the
    ///      bounty posted.
    function reclaimBounty(uint32 puzzleId) external nonReentrant {
        if (msg.sender != admin) revert NotAdmin();

        PuzzleMeta memory meta = puzzleMeta[puzzleId];
        if (meta.bounty == 0 || meta.claimedBy != address(0)) revert NothingToReclaim();
        puzzleMeta[puzzleId].bounty = 0;

        emit BountyReclaimed(puzzleId, admin, meta.bounty);

        if (paymentToken == address(0)) {
            (bool ok,) = admin.call{value: meta.bounty}("");
            if (!ok) revert TransferFailed();
        } else {
            IERC20(paymentToken).safeTransfer(admin, meta.bounty);
        }
    }

    // -----------------------------------------------------------------------
    // Verification
    // -----------------------------------------------------------------------

    /// @notice Submit and verify a claim.
    /// @param puzzleId The registered puzzle this claim is against.
    /// @param claim The packed claim bytes (see `ClaimCodec`).
    /// @return ok True iff all four checks pass.
    ///
    /// @dev Returns `false` and emits `Rejected` rather than reverting, matching
    ///      the Soroban contract. A revert would refund the remaining gas, but
    ///      for a paid service an on-chain record of *why* a claim failed is
    ///      worth more than the refund.
    function submitAndVerify(uint32 puzzleId, bytes calldata claim)
        external
        payable
        nonReentrant
        returns (bool ok)
    {
        _collectFee();

        PuzzleMeta memory meta = puzzleMeta[puzzleId];
        if (meta.puzzleHash == bytes32(0)) {
            emit Rejected(puzzleId, msg.sender, 0);
            return false;
        }

        ClaimCodec.ClaimView memory v = ClaimCodec.decode(claim);

        // --- 1. Header Merkle -> puzzleHash --------------------------------
        // leaf = SHA-256( r || r_dot_m_xor_s_be32 || bitmap || msg.sender )
        // The trailing bytes20 binds the claim to the submitting account: a
        // claim is worthless from any other address, so an observed
        // transaction cannot be front-run to steal the bounty.
        bytes32 headerLeaf = sha256(
            abi.encodePacked(
                ClaimCodec.slice(v.rOff, v.rLen),
                uint32(v.rDotMXorS),
                ClaimCodec.slice(v.bitmapOff, v.bitmapLen),
                msg.sender
            )
        );
        if (
            !Merkle.verifyFromCursor(
                Cursor.init(v.headerPathOff, v.end - v.headerPathOff), headerLeaf, meta.puzzleHash
            )
        ) {
            emit Rejected(puzzleId, msg.sender, 1);
            return false;
        }

        // --- 2 + 3. Per-gate Merkle binding, then the Yao spot-check -------
        uint256 k = v.spotChecks.length;
        for (uint256 i = 0; i < k; ++i) {
            ClaimCodec.SpotCheckView memory sc = v.spotChecks[i];

            // leaf = SHA-256( table_4x16B || gate_index_be32 )
            bytes32 gateLeaf =
                sha256(abi.encodePacked(ClaimCodec.slice(sc.tableOff, 64), sc.gateIndex));
            if (
                !Merkle.verifyFromCursor(
                    Cursor.init(sc.pathOff, v.end - sc.pathOff), gateLeaf, meta.puzzleHash
                )
            ) {
                emit Rejected(puzzleId, msg.sender, 2);
                return false;
            }

            // The gate must be one the puzzle declared non-reusable. Without
            // this a solver could spot-check a gate they trivially control.
            if (!ClaimCodec.isNonReusable(v, sc.gateIndex)) {
                emit Rejected(puzzleId, msg.sender, 3);
                return false;
            }

            if (!SpotCheck.verifyOneCalldata(sc.kL, sc.kR, sc.kO, sc.tableOff, sc.gateIndex)) {
                emit Rejected(puzzleId, msg.sender, 3);
                return false;
            }
        }

        // --- 4. Goldreich-Levin --------------------------------------------
        // gf2(r, y) XOR s_claim == r_dot_m_xor_s
        uint8 lhs = InnerProduct.gf2Calldata(v.rOff, v.yOff, v.rLen) ^ v.sClaim;
        if (lhs != v.rDotMXorS) {
            emit Rejected(puzzleId, msg.sender, 4);
            return false;
        }

        // --- 5. Settle the bounty -------------------------------------------
        // The claim was valid, so pay the solver in the same transaction.
        // Effects (claim marker) strictly before the interaction (transfer);
        // `nonReentrant` plus the marker close the double-payout paths. A
        // bounty-less puzzle keeps the old semantics: every honest claim
        // verifies, any number of times.
        uint96 bounty = meta.bounty;
        if (bounty != 0) {
            if (meta.claimedBy != address(0)) {
                emit Rejected(puzzleId, msg.sender, 5);
                return false;
            }
            puzzleMeta[puzzleId].claimedBy = msg.sender;

            emit Verified(puzzleId, msg.sender, sha256(claim), v.sClaim);
            emit BountyPaid(puzzleId, msg.sender, bounty);

            if (paymentToken == address(0)) {
                (bool sent,) = msg.sender.call{value: bounty}("");
                if (!sent) revert TransferFailed();
            } else {
                IERC20(paymentToken).safeTransfer(msg.sender, bounty);
            }
            return true;
        }

        emit Verified(puzzleId, msg.sender, sha256(claim), v.sClaim);
        return true;
    }

    // -----------------------------------------------------------------------
    // Views
    // -----------------------------------------------------------------------

    /// @notice Read a puzzle's metadata.
    function puzzleMetaOf(uint32 puzzleId) external view returns (PuzzleMeta memory) {
        return puzzleMeta[puzzleId];
    }

    /// @notice True iff `puzzleId` has been registered.
    function puzzleExists(uint32 puzzleId) external view returns (bool) {
        return puzzleMeta[puzzleId].puzzleHash != bytes32(0);
    }

    // -----------------------------------------------------------------------
    // Internals
    // -----------------------------------------------------------------------

    /// @dev Pull the fee before any verification work.
    ///
    ///      Three modes, which is a deliberate change from the Soroban contract:
    ///      there, a fee was collected only if *both* `fee > 0` and a payment
    ///      token was set, so `fee > 0` with no token silently meant "free".
    ///      Here `paymentToken == address(0)` unambiguously means native ETH.
    function _collectFee() private {
        uint256 fee = feePerVerify;
        if (fee == 0) {
            if (msg.value != 0) revert UnexpectedValue();
            return;
        }

        if (paymentToken == address(0)) {
            if (msg.value != fee) revert WrongFee(fee, msg.value);
        } else {
            if (msg.value != 0) revert UnexpectedValue();
            IERC20(paymentToken).safeTransferFrom(msg.sender, address(this), fee);
        }

        totalCollected += fee;
    }
}
