// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {QuantumVerifier} from "../src/QuantumVerifier.sol";

/// @title Deploy
/// @notice Deploys the verifier. Set via env:
///   ADMIN_ADDRESS       (default: msg.sender)
///   PAYMENT_TOKEN       (default: address(0) => native ETH; set to a token for
///                        free mode, set FEE_PER_VERIFY=0)
///   FEE_PER_VERIFY      (default: 0 => free mode)
contract Deploy is Script {
    function run() external returns (QuantumVerifier v) {
        address admin_ = vm.envOr("ADMIN_ADDRESS", msg.sender);
        address token_ = vm.envOr("PAYMENT_TOKEN", address(0));
        uint256 fee_ = vm.envUint("FEE_PER_VERIFY");

        uint256 pk = vm.envUint("PRIVATE_KEY");
        vm.startBroadcast(pk);

        v = new QuantumVerifier(admin_, token_, fee_);

        vm.stopBroadcast();

        console2.log("QuantumVerifier deployed at", address(v));
        console2.log("admin:", admin_);
        console2.log("paymentToken:", token_);
        console2.log("feePerVerify:", fee_);
    }
}
