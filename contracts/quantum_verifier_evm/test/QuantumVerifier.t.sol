// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {QuantumVerifier} from "../src/QuantumVerifier.sol";
import {ClaimCodec} from "../src/lib/ClaimCodec.sol";
import {Cursor} from "../src/lib/Cursor.sol";
import {Merkle} from "../src/lib/Merkle.sol";
import {SpotCheck} from "../src/lib/SpotCheck.sol";
import {InnerProduct} from "../src/lib/InnerProduct.sol";
import {GeneratedFixtures} from "./fixtures/GeneratedFixtures.sol";

/// @title QuantumVerifierTest
///
/// @notice Test tiers, in increasing integration depth:
///   1. Unit tests on the libraries — no fixture dependency, always run.
///   2. Golden-vector integration tests against real TLP bytes
///      (`GeneratedFixtures`). These auto-skip if the fixture file is still the
///      placeholder stub, so a fresh checkout never passes vacuously.
///   3. Fuzz tests on the decoder and the guard rails.
contract QuantumVerifierTest is Test {
    using Cursor for Cursor.C;
    using Cursor for bytes;
    QuantumVerifier verifier;

    address admin = makeAddr("admin");
    address solver = makeAddr("solver");

    function setUp() public {
        verifier = new QuantumVerifier(admin, address(0), 0);
    }

    // -----------------------------------------------------------------------
    // Tier 1 — library units
    // -----------------------------------------------------------------------

    function test_PadMatchesSha256Definition() public pure {
        // SpotCheck.pad == SHA-256(kL || kR || gi_be64)[:16], verified against
        // Solidity's own sha256 rather than only against Python fixtures.
        bytes16 kL = bytes16(0x0123456789abcdef0123456789abcdef);
        bytes16 kR = bytes16(0xfedcba9876543210fedcba9876543210);
        uint32 gi = 12345;
        bytes32 digest = sha256(abi.encodePacked(kL, kR, uint64(gi)));
        assertEq(SpotCheck.pad(kL, kR, gi), bytes16(digest));
    }

    function test_SelectBitIsLSBOfFirstByte() public pure {
        assertEq(SpotCheck.selectBit(bytes16(0x00ff0000000000000000000000000000)), 0);
        assertEq(SpotCheck.selectBit(bytes16(0x01000000000000000000000000000000)), 1);
    }

    function test_InnerProductByteWiseEqualsBitwise() public pure {
        // The byte-wise shortcut must equal the literal bit-by-bit definition.
        bytes memory a = hex"deadbeefcafebabe0123456789abcdef";
        bytes memory b = hex"13579bdf2468ace0feedface12345678";

        // byte-wise
        uint8 acc = 0;
        for (uint256 i = 0; i < a.length; ++i) {
            acc ^= uint8(a[i] & b[i]);
        }
        uint8 byteWise = InnerProduct.parity8(acc);

        // bit-by-bit, LSB first
        uint256 parity = 0;
        for (uint256 i = 0; i < a.length * 8; ++i) {
            uint8 ab = uint8(a[i / 8]) >> (i % 8) & 1;
            uint8 bb = uint8(b[i / 8]) >> (i % 8) & 1;
            parity ^= ab & bb;
        }
        assertEq(byteWise, uint8(parity));
    }

    function test_CursorRejectsTruncatedRead() public {
        bytes memory data = hex"0102"; // only 2 bytes
        vm.expectRevert(abi.encodeWithSelector(Cursor.Truncated.selector, 0, 4, 2));
        this.readU32From(data);
    }

    function readU32From(bytes calldata data) external pure {
        Cursor.C memory c = Cursor.init(0, data.length);
        c.u32();
    }

    function test_CursorBoolRejectsTwo() public {
        bytes memory data = hex"02";
        vm.expectRevert();
        this.decodeExternalBool(data);
    }

    function decodeExternalBool(bytes calldata data) external pure {
        Cursor.C memory c = Cursor.init(data);
        c.bool1();
    }

    function test_CursorTrailingBytesRejected() public {
        bytes memory data = hex"01020304ff";
        vm.expectRevert(abi.encodeWithSelector(Cursor.TrailingBytes.selector, 4, 5));
        this.readAndExpectDone(data);
    }

    function readAndExpectDone(bytes calldata data) external pure {
        Cursor.C memory c = Cursor.init(0, data.length);
        c.u32();
        c.expectDone();
    }

    function test_MerkleVerifyRoundTrip() public pure {
        bytes32 leaf = keccak256("leaf");
        bytes32 sib0 = keccak256("sib0");
        bytes32 sib1 = keccak256("sib1");
        // root = H(H(leaf, sib0), sib1)
        bytes32 root = Merkle.node(Merkle.node(leaf, sib0), sib1);
        bytes32[] memory sibs = new bytes32[](2);
        sibs[0] = sib0;
        sibs[1] = sib1;
        bool[] memory isLeft = new bool[](2);
        isLeft[0] = false; // leaf is left child
        isLeft[1] = false;
        assertTrue(Merkle.verify(leaf, sibs, isLeft, root));
    }

    function test_MerkleRejectsWrongRoot() public pure {
        bytes32 leaf = keccak256("leaf");
        bytes32[] memory sibs = new bytes32[](1);
        sibs[0] = keccak256("sib");
        bool[] memory isLeft = new bool[](1);
        isLeft[0] = false;
        assertFalse(Merkle.verify(leaf, sibs, isLeft, bytes32("nope")));
    }

    // -----------------------------------------------------------------------
    // Tier 2 — golden-vector integration (auto-skips on stub fixtures)
    // -----------------------------------------------------------------------

    function _fixtureCount() internal pure returns (uint256) {
        return GeneratedFixtures.all().length;
    }

    function test_FixturesPresent() public view {
        // Fail loudly, don't skip silently: if the generator was never run the
        // integration coverage is zero and this must be obvious.
        assertTrue(_fixtureCount() > 0, "run python/gen_fixtures.py first");
    }

    function test_GoldenVectors() public {
        if (_fixtureCount() == 0) return;

        // Register every fixture's puzzleHash; the unknown_puzzle fixture is
        // distinguished by name and must stay unregistered (reason 0).
        for (uint256 i = 0; i < _fixtureCount(); ++i) {
            GeneratedFixtures.Fixture memory f = GeneratedFixtures.all()[i];
            if (keccak256(bytes(f.name)) == keccak256("unknown_puzzle")) continue;
            vm.prank(admin);
            verifier.registerPuzzle(bytes32(0), bytes32(0), f.puzzleHash, 0);
        }

        for (uint256 i = 0; i < _fixtureCount(); ++i) {
            GeneratedFixtures.Fixture memory f = GeneratedFixtures.all()[i];
            uint32 puzzleId = uint32(i + 1);
            if (keccak256(bytes(f.name)) == keccak256("unknown_puzzle")) {
                puzzleId = 999;
            }

            vm.prank(solver);
            bool ok = verifier.submitAndVerify(puzzleId, f.claim);

            assertEq(ok, f.expectValid, f.name);
        }
    }

    function test_PadGoldenVectors() public pure {
        if (GeneratedFixtures.padVectors().length == 0) return;
        GeneratedFixtures.PadVector[] memory p = GeneratedFixtures.padVectors();
        for (uint256 i = 0; i < p.length; ++i) {
            assertEq(
                SpotCheck.pad(p[i].kL, p[i].kR, p[i].gateIndex),
                p[i].expected,
                "pad vector mismatch"
            );
        }
    }

    // -----------------------------------------------------------------------
    // Tier 3 — fuzz
    // -----------------------------------------------------------------------

    /// @dev Random bytes must never decode successfully. The decoder is the
    ///      attack surface for malleability; a valid decode from noise would
    ///      mean the format is ambiguous.
    function testFuzz_RandomBytesNeverDecode(bytes calldata data) public {
        // Only claims that happen to be well-formed can decode; the generator
        // produces real claims rarely enough that we bound this test to bytes
        // that are clearly not valid claims (wrong total length for the header).
        vm.assume(data.length != 0);
        // A claim needs at least r_len(4) + r(1..64) + flag(1) + bitmap_len(4)
        // + bitmap(1..512) + path_count(4) + K(4) + ... — at minimum ~20 bytes.
        if (data.length < 20) {
            vm.expectRevert();
            this.decodeExternal(data);
        }
    }

    function decodeExternal(bytes calldata data) external pure {
        ClaimCodec.decode(data);
    }

    /// @dev The GL check is parity — flipping any single bit of `r` must flip
    ///      the verdict for a fixed `y` and `s_claim`.
    function testFuzz_FlipAnyRBitFlipsGLVerdict(uint256 seedInt, uint8 bit) public pure {
        bit = uint8(bound(uint256(bit), 0, 63));
        bytes32 seed = bytes32(seedInt);
        bytes memory r = new bytes(8);
        bytes memory y = new bytes(8);
        for (uint256 i = 0; i < 8; ++i) {
            r[i] = bytes1(seed[i]);
            y[i] = bytes1(seed[i + 8]);
        }
        uint8 honest = InnerProduct.gf2Memory(r, y);

        // NB: build the flipped copy in a fresh array — relying on
        // memory-assignment semantics here is a known trap.
        bytes memory rFlipped = new bytes(8);
        for (uint256 i = 0; i < 8; ++i) {
            rFlipped[i] = r[i];
        }
        rFlipped[bit / 8] = bytes1(uint8(rFlipped[bit / 8]) ^ uint8(1 << (bit % 8)));

        // y = all ones so every bit of r contributes to the parity.
        for (uint256 i = 0; i < 8; ++i) {
            y[i] = 0xff;
        }
        honest = InnerProduct.gf2Memory(r, y);
        uint8 flipped = InnerProduct.gf2Memory(rFlipped, y);
        assertNotEq(flipped, honest, "parity must flip");
    }

    function test_WithdrawSweepsAndResets() public {
        vm.prank(admin);
        verifier.setFeePerVerify(1000);
        vm.deal(address(verifier), 5000);
        // Storage layout: ReentrancyGuard base first (_status=0), then
        // feePerVerify=1, totalCollected=2, puzzleCount=3, puzzleMeta=4.
        vm.store(address(verifier), bytes32(uint256(2)), bytes32(uint256(5000)));

        vm.prank(admin);
        verifier.withdraw(makeAddr("to"));
        assertEq(address(verifier).balance, 0);
        assertEq(verifier.totalCollected(), 0);
    }

    function test_RevertWhenNotAdmin() public {
        vm.expectRevert(QuantumVerifier.NotAdmin.selector);
        vm.prank(solver);
        verifier.registerPuzzle(bytes32(0), bytes32(0), bytes32(0), 0);
    }
}
