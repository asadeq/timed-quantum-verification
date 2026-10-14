// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../interfaces/IERC20.sol";

/// @title SafeERC20 — ERC-20 calls that tolerate non-standard tokens.
///
/// @dev USDC and most majors return `true`, but some widely used tokens return
///      nothing at all. A bare `IERC20(token).transfer(...)` that ignores the
///      return value silently succeeds against a token that returned `false`,
///      and reverts against one that returned nothing. Both are wrong.
library SafeERC20 {
    error SafeERC20FailedOperation(address token);

    function safeTransfer(IERC20 token, address to, uint256 value) internal {
        _callOptionalReturn(token, abi.encodeCall(IERC20.transfer, (to, value)));
    }

    function safeTransferFrom(IERC20 token, address from, address to, uint256 value) internal {
        _callOptionalReturn(token, abi.encodeCall(IERC20.transferFrom, (from, to, value)));
    }

    function _callOptionalReturn(IERC20 token, bytes memory data) private {
        (bool success, bytes memory returndata) = address(token).call(data);
        if (!success || (returndata.length != 0 && !abi.decode(returndata, (bool)))) {
            revert SafeERC20FailedOperation(address(token));
        }
    }
}
