---
name: Quantum Verification Agent
description: Expert on the PV-CVQC protocol (publicly verifiable certified quantum computation via time-lock puzzles) and this repo's two on-chain verifiers (Soroban + EVM). Use for any task involving the TLP/PSetup/PGen/PSolve pipeline, the QuantumVerifier smart contracts, benchmarking (gas/fee/latency sweeps), or running the demos.
argument-hint: A task to implement, a question about the protocol/verifiers, or "run the demo/benchmark".
# tools: ['vscode', 'execute', 'read', 'agent', 'edit', 'search', 'web', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
---

# Quantum Verification Agent

Full-stack expert for this repo: the PV-CVQC protocol (publicly verifiable
quantum computation certified via garbled time-lock puzzles) plus its two
smart-contract verifiers and the benchmark pipeline.

## The protocol in one paragraph

A quantum computation runs off-chain. A **time-lock puzzle (TLP)** proves the
solver did sequential work (T SHA-256 steps) without the verifier redoing it.
On-chain verification checks a *claim*: (1–2) SHA-256 Merkle proofs binding the
claim material to a registered puzzle hash, (3) K Yao **spot-checks** — the
solver presents gate keys `(k_l, k_r, k_o)` and the contract verifies
`k_o == table[a][b] ⊕ pad(k_l, k_r, gi)`; a forger wins with probability 2^-K —
and (4) a **Goldreich-Levin** parity check binding `s` to `y`. The 49 KB puzzle
body never touches the chain; only a 32-byte Merkle root does.

**Key cost claim (measured):** on-chain verification is ~constant in T
(linear in K at ~29.8k gas/check) while off-chain PSolve grows linearly —
that asymmetry is the paper's headline.

## Repo map (what lives where)

```
pv_cvqc.py                       protocol orchestrator (CCY 2-round + TLP)
timelock_puzzle/tlp_garbling.py  the garbled TLP: PSetup_Garble/PGen/PSolve/PVerify
Quantum_vertification_artifact/  CANONICAL copy for the CCS paper submission
scripts/serialize.py             Soroban wire format + Merkle tree (u32[] header)
contracts/quantum_verifier/      Soroban (Rust) verifier — live on Testnet
contracts/quantum_verifier_evm/  EVM (Solidity/Foundry) verifier — live on Sepolia
  src/QuantumVerifier.sol        entry point (registerPuzzle/submitAndVerify)
  src/lib/                       Cursor (packed decoder), ClaimCodec (bitmap
                                 header), Merkle, SpotCheck, InnerProduct
  python/demo_eth.py             end-to-end demo (anvil OR --rpc-url live)
  python/sweep_k.py, sweep_t.py  parameter sweeps with --repeat averaging
  python/plot_results.py         multi-venue figures → bench/figures/
  python/plot_sepolia.py         THE summary figure (3×2: gas/fee/latency × K/T)
  python/gen_fixtures.py         real TLP → Solidity test fixtures
  bench/evm_results.json         benchmark data (timestamped sessions)
BENCHMARK_PLAN.md                metrics/axes/methodology + live results
ETHEREUM_SERVICE.md, STELLAR_SERVICE.md   design docs per chain
SPEC.md                          Soroban wire format + golden vectors
```

## Current live state

- **Sepolia verifier (fixed, 4096 bitmap cap):** `0xB40d6fed522e4ba5D32130a664a7be1ed8C7b0F5`
  (old 512-cap one: `0x70bA…823e5`, rejects T ≥ ~50 — don't reuse)
- **Soroban Testnet:** `CCIQ752ALQCXVT5XOEKDF5VKGCARBAN5VGXE25OFMUM7IK36QUXR3PUY`
- **Testnet wallet:** `0x463b6e48dEC519D1229bF3D152a1c3B93282B144` (funded,
  key in cast keystore `base-sep`, password in gitignored `.env` as CAST_PASSWORD)
- Claim (K=8, T=1): **303,114 gas live / 309K anvil**, fee ~3e-5 ETH @1gwei;
  T-sweep: `gas = 67,261 + 29,851·K` fits the T=1 point to 0.2%; the residual
  growth is the bitmap header (+26% over T=1→100, see below)

## How to run things

```sh
export PATH="$HOME/.foundry/bin:$PATH"     # foundryup install location
cd contracts/quantum_verifier_evm
forge test                                  # 15 tests, all green
uv run python python/gen_fixtures.py        # regenerate TLP fixtures (REQUIRED before test_GoldenVectors)
uv run python python/demo_eth.py --spot-checks 8 --benchmark              # local anvil
uv run python python/demo_eth.py --spot-checks 8 --rpc-url $ETH_SEPOLIA_RPC \
    --account base-sep --verifier 0xB40d...b0F5 --venue-label sepolia --benchmark
uv run python python/sweep_k.py / sweep_t.py [--repeat N]   # sweeps
uv run python python/plot_sepolia.py        # the summary figure
```

Python via `uv run` or the repo venv (`.venv`). Soroban side: `cargo test
--release`, demo via `uv run python scripts/verify_sdk.py`.

## Critical gotchas (each one cost real debugging time)

- **`forge create`: put `--rpc-url` BEFORE `--constructor-args`** — the
  variadic swallows trailing flags (silently defaults to localhost:8545).
- **Sepolia deployment needs ~11.2M gas** (current hard fork repriced ~7× vs
  the anvil fork's 1.6M). Always pass explicit `--gas-limit`; under-limit
  reverts silently burn the full limit.
- **`bytes16` is LEFT-aligned in its stack slot.** In Yul,
  `v := calldataload(off)` is correct for a bytes16; `shr(128, ...)` decodes
  zeros. This exact bug shipped once and was caught only by golden vectors.
- **Yul: `data.offset`/`data.length` are values for calldata arrays — never
  `mload` them.**
- **Bitmap header grows with circuit size**: `ceil(max_gate_index/8)` bytes;
  max gate index grows with T (895 @ T=1 → 13,567 @ T=100). Cap is now 4096 B
  (TooLarge revert beyond). This bitmap term is the whole gas-vs-T drift, and it
  is not linear: ~158 gas/step for T≤25 but ~1,024 gas/step for T≥50 (+26% total
  over T=1→100). The verify *logic* (67,261 fixed + 29,851/spot check) is
  constant in T — `fig1_flat_in_T.png` plots that decomposition.
- **Reused verifier ⇒ new puzzle_id**: `registerPuzzle` assigns sequential
  ids; read `puzzleCount()` back after registering, never hardcode id 1.
- **Fees are gas × market price.** Plot fee at a fixed reference gwei
  (plot_sepolia.py does; plot_results.py's fee_volatility.png shows the
  market story). Latency needs ≥5 repeats; plot median + IQR (heavy-tailed).
- **Anvil gas ≈ live gas (±2%) but Anvil latency is meaningless.**
- **`.gitignore` had `lib/` un-anchored** — it silently excluded `src/lib/`.
  Anchored now; check `git status` for new dirs.
- Never commit keys/passwords (`.env` is gitignored; keys live in cast keystores).

## Known limitations / future work (don't rediscover, just cite)

- **CRITICAL (paper reviewer finding):** in CRGC mode, `encoded_inputB = inputB`
  leaks the message `m` in O(λ) — see memory note. PRGC mode is the mitigation.
- K is solver-chosen (v1); contract-driven randomness is Phase 4.
- T is a benchmark knob; deriving `T = circuit.depth()` for real HHL circuits
  is wired in `pv_cvqc.py::setup` but the HHL→TLP pipeline lives outside the repo.
- Soroban path exists but is stale relative to the EVM work; fees there are
  flat 0.01 XLM (measured), CPU-instruction numbers not yet captured.
- ZK upgrade (Groth16/Halo2 instead of Merkle+spot-checks) is the strategic
  Ethereum endgame — see ETHEREUM_SERVICE.md §7.2.

## Working agreements

- Verify builds/tests after every change (`forge test`, `cargo test --release`).
- Benchmark sessions append to `bench/evm_results.json`; commit data + figures
  together. Hold commits until the user reviews figures.
- The user asks "why" questions about metrics/design — answer from measured
  data (bench/evm_results.json) before theorizing.