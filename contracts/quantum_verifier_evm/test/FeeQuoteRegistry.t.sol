// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {FeeQuoteRegistry} from "../src/FeeQuoteRegistry.sol";

contract FeeQuoteRegistryTest is Test {
    FeeQuoteRegistry registry;
    address server = makeAddr("server");
    address client = makeAddr("client");

    event QuoteSet(address indexed server, uint96 marginWei);

    function setUp() public {
        registry = new FeeQuoteRegistry();
    }

    function test_UnpricedServerReadsZero() public view {
        assertEq(registry.quoteOf(server), 0, "unpriced server must read 0");
    }

    function test_SetQuoteStoresAndEmits() public {
        vm.expectEmit(true, false, false, true);
        emit QuoteSet(server, 166_666_666_666_667);
        vm.prank(server);
        registry.setQuote(166_666_666_666_667); // $0.50 @ ETH=$3000

        assertEq(registry.quoteOf(server), 166_666_666_666_667);
    }

    function test_OverwriteTakesLatest() public {
        vm.startPrank(server);
        registry.setQuote(1 ether);
        registry.setQuote(2 ether);
        vm.stopPrank();
        assertEq(registry.quoteOf(server), 2 ether, "latest quote wins");
    }

    function test_QuotesArePerServer() public {
        vm.prank(server);
        registry.setQuote(1 ether);
        assertEq(registry.quoteOf(client), 0, "other servers unaffected");
    }

    function test_ZeroQuoteRejected() public {
        vm.prank(server);
        vm.expectRevert(FeeQuoteRegistry.ZeroQuote.selector);
        registry.setQuote(0);
    }

    function testFuzz_SetQuote(uint96 marginWei) public {
        vm.assume(marginWei != 0);
        vm.prank(server);
        registry.setQuote(marginWei);
        assertEq(registry.quoteOf(server), marginWei);
    }
}
