// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title FeeQuoteRegistry — where the quantum server publishes its price.
///
/// @notice The service price for a verified claim is the bounty the client
///         escrows at `QuantumVerifier.registerPuzzle`. The bounty has two
///         legs: the estimated verification gas (a pass-through the client
///         covers at cost, priced from the measured gas model) and the
///         server's margin — the labor price for the sequential `PSolve`
///         work. Only the server knows what that labor is worth, so the
///         server publishes it here and the client reads it before escrowing.
///
///         The quote is a *discovery* mechanism, not an enforcement one: the
///         bounty still pays whatever was escrowed. The server's acceptance
///         remains implicit — it checks the bounty against its quote before
///         submitting, and simply refuses (does no work) if the client
///         underpaid. Escrow-before-work is what makes that refusal safe:
///         the server never hands over `y` against an unfunded promise, and
///         the client reclaims via `reclaimBounty` when no server accepts.
///
/// @dev One flat margin per server. The server's labor scales with T
///      (`PSolve` ~33 µs/step), not with K — K only drives the gas leg, which
///      is reimbursed 1:1 — so a flat labor price is the honest shape at toy
///      scale; a per-T quote is the natural v2.
contract FeeQuoteRegistry {
    /// @dev server => margin in wei per verified claim.
    mapping(address => uint96) private _marginWei;

    event QuoteSet(address indexed server, uint96 marginWei);

    error ZeroQuote();

    /// @notice Publish (or update) the server's margin per verified claim.
    /// @param marginWei The server's labor price in wei. Must be nonzero;
    ///        a server that wants to stop serving should not be representable
    ///        as "quote 0" — it just stops accepting (clients read 0 as
    ///        "no quote published" and must not confuse that with free).
    function setQuote(uint96 marginWei) external {
        if (marginWei == 0) revert ZeroQuote();
        _marginWei[msg.sender] = marginWei;
        emit QuoteSet(msg.sender, marginWei);
    }

    /// @notice The server's quoted margin per verified claim.
    /// @return 0 means "no quote published" — the client must not escrow
    ///         against an unpriced server.
    function quoteOf(address server) external view returns (uint96) {
        return _marginWei[server];
    }
}
