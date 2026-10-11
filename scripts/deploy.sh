#!/usr/bin/env bash
# Build, optimize, deploy, and initialize the quantum verifier on Testnet.
#
# Usage:
#   ./scripts/deploy.sh              # deploy + init, print the contract id
#
# Then run the end-to-end demo:
#   uv run python scripts/verify_sdk.py --contract <C...> --spot-checks 8
#
# NOTE: rebuild is intentional here — the integration tests load the wasm
# via include_bytes!, and cargo test does NOT rebuild the wasm target.
# Skipping this step silently tests/deploy stale bytecode.

set -euo pipefail

NETWORK="testnet"
ALICE="alice"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTRACT_DIR="${REPO_ROOT}/contracts/quantum_verifier"
WASM="${CONTRACT_DIR}/target/wasm32v1-none/release/quantum_verifier.wasm"
OPT_WASM="${CONTRACT_DIR}/target/wasm32v1-none/release/quantum_verifier.optimized.wasm"

echo "==> 1. Building wasm (wasm32v1-none)..."
( cd "$CONTRACT_DIR" && cargo build --release --target wasm32v1-none )

echo "==> 2. Optimizing wasm..."
stellar contract optimize --wasm "$WASM" 2>/dev/null \
    || ( cd "$CONTRACT_DIR" && stellar contract build --optimize )
echo "   $(wc -c < "$OPT_WASM" | tr -d ' ') bytes"

echo "==> 3. Deploying to $NETWORK..."
DEPLOY_OUTPUT=$(stellar contract deploy --wasm "$OPT_WASM" \
    --source "$ALICE" --network "$NETWORK" 2>&1) || {
    # TxBadSeq etc. — one retry after a short pause.
    sleep 5
    DEPLOY_OUTPUT=$(stellar contract deploy --wasm "$OPT_WASM" \
        --source "$ALICE" --network "$NETWORK" 2>&1)
}
CONTRACT_ID=$(echo "$DEPLOY_OUTPUT" | tail -1)
echo "   contract = $CONTRACT_ID"

echo "==> 4. Initializing (admin=alice, free mode)..."
ALICE_ADDRESS=$(stellar keys address "$ALICE")
sleep 3
stellar contract invoke --id "$CONTRACT_ID" --source "$ALICE" \
    --network "$NETWORK" -- init \
    --admin "$ALICE_ADDRESS" --fee_per_verify 0 > /dev/null
echo "   done."

echo
echo "Deployed contract: $CONTRACT_ID"
echo
echo "Run the demo:"
echo "  uv run python scripts/verify_sdk.py --contract $CONTRACT_ID --spot-checks 8"
