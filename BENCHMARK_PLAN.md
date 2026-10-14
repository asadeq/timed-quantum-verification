# Benchmark Plan — On-Chain vs Off-Chain Verification

> Companion to [ETHEREUM_SERVICE.md](ETHEREUM_SERVICE.md) and
> [STELLAR_SERVICE.md](STELLAR_SERVICE.md). Defines the metrics, axes, and
> experiment matrix for comparing smart-contract verification against the
> plain-Python verifier, and quantifying how each scales with puzzle size and
> HHL/quantum-circuit size.

## The question the benchmarks answer

**What does on-chain verification cost, and how does that cost behave as the
certified computation grows?**

The headline result to *demonstrate*, not just measure: the chain's cost is
**constant in T** while everything off-chain scales. A flat line in a
gas-vs-T plot *is* the protocol's central claim, made quantitative.

---

## 1. Cost metrics (on-chain)

| Metric | How to measure | Why it matters |
|---|---|---|
| **Gas per verification** | `cast receipt <tx> --json \|.gasUsed`, or in-process gas snapshots in `forge test` | The EVM's native "CPU cost" unit |
| **Gas breakdown by phase** | `forge test -vvvv` trace; or `gasleft()` diffs around each check | Shows the Merkle / spot-check / GL split |
| **Calldata bytes vs execution gas** | claim `len(data)` vs `receipt.gasUsed` | Proves calldata dominates (~77% today) — the key cost lever |
| **Fee in native token / USD** | `gasUsed × effectiveGasPrice` × token price | The number a user actually pays |
| **Fee vs solver's off-chain cost** | fee vs PSolve wall-clock | "Verification amplification ratio" — the headline economics |
| **Fee per venue** | rerun on Sepolia / Base Sepolia | Local Anvil gas ≠ production economics (base fee, blob pricing) |
| **Storage cost per registration** | gas of `registerPuzzle` (one-time) | Separates fixed vs per-claim cost |
| **Soroban equivalents** | CPU instructions + stroop fee per `submit_and_verify` | Apples-to-apples cross-chain table |

**Known anchors** (measured 2026-10, `contracts/quantum_verifier_evm`,
golden-vector fixtures): K=1 → **103,812 gas**; K=8 → **312,010 gas**
(~309,138 measured through the full demo tx path). Soroban demo today: flat
0.01 XLM per call.

## 2. Latency metrics

| Metric | What it captures |
|---|---|
| **RPC submit latency** | wall-clock: sign tx → tx accepted |
| **Inclusion time** | submit → receipt (L1 ~12 s, L2 ~250 ms, Anvil ~0) |
| **Finality time** | submit → verdict irreversible — **the number a service user feels** |
| **Total verify path** | PSolve end → on-chain verdict, end to end |
| **Client-side overhead** | claim serialization + Merkle path building (pure Python) |
| **Python `PVerify` wall-clock** | the "no blockchain" baseline this whole comparison exists for |

⚠️ **Anvil finality is instant** — latency numbers from the local demo are not
representative. Measure latency on real testnets.

## 3. Off-chain baseline metrics

Already largely instrumented:

| Source | What it has |
|---|---|
| `pv_cvqc.py` | `setup_time, garbling_time, generation_time, prove_time, reveal_time, verify_time` |
| `benchmark_tlp.py` | garbling / PGen / PSolve times swept over T (5 trials) → `tlp_benchmark_results.json` |
| `benchmark_tlp_random.py` | richer T=1..30 sweep, per-puzzle `gen_time_ms` / `solve_time_ms` + mean±std → `benchmark_results_T1_30/` |
| `benchmark_qiskit_random.py` | Qiskit circuit gen/transpile/exec times by qubits×depth → `benchmark_results_qiskit_random/` |
| `generate_latex_table.py` | joins TLP + Qiskit JSONs into `benchmark_table*.tex` |

**Gap:** the benchmarks time PSolve, but the thing being *replaced* is
`PVerify`. Add a `PVerify`-only timing loop as the baseline.

## 4. Scaling axes — and expected behaviour

### Axis A: T (time-lock length / circuit depth)

| Cost | Behaviour in T |
|---|---|
| Garbling (`PSetup_Garble`) | grows ~linearly |
| Puzzle generation (`PGen`) | grows ~linearly |
| Solving (`PSolve`) | grows ~linearly (T sequential SHA-256 steps) |
| Python `PVerify` | grows with circuit size |
| **Claim size** | **constant** — depends on K and non-reusable gate count, not T |
| **On-chain gas** | **flat** — T enters only the 13-byte `CircuitSpec` hash |

Second-order effect: larger circuits can change the non-reusable gate count,
which grows the puzzle body (off-chain) and the EVM bitmap header at
⌈max_gate_index/8⌉ bytes → mild, sub-linear gas growth via header hashing.
Expect near-flat with small steps, not a perfectly straight line.

### Axis B: HHL / quantum problem size

Less clean today: **T is currently a benchmark knob, not derived from the
circuit.** `pv_cvqc.py::setup` already sketches the wiring
(`T = hist_circuit.depth()`), and `hhl_tlp.ipynb` shows HHL depth ~251 for a
small problem — but the explicit HHL→TLP pipeline lives outside this repo
(`puzzle_generation/puzzle.json`).

To make HHL size a real axis:

1. Pick HHL problems of growing dimension / condition number
   (`enhanced_hybrid_hhl/` + `hhl_example.py`).
2. Set `T = f(circuit depth)`.
3. Plot all metrics against problem size.

**Hold `lam`, `msg_bits`, and K fixed** while varying T/depth — otherwise two
variables move at once and the flat-line result gets muddy.

### Axis C: K (spot-check count) — the security/cost dial

Gas grows linearly in K; cheating probability falls as $2^{-K}$.
Sweep K ∈ {1, 2, 4, 8, 16, 32} → a **security-per-gas frontier**.
Anchor points: 103,812 gas (K=1) → 312,010 (K=8); extrapolate K=16 ≈ 470 K,
K=32 ≈ 790 K (calldata-dominated).

## 5. Experiment matrix

```
Axis 1: T ∈ {1, 5, 10, 25, 50, 100}          (time-lock growth)
Axis 2: HHL problem size (→ depth → T)
Axis 3: K ∈ {1, 2, 4, 8, 16, 32}             (security dial)
Axis 4: venue ∈ {Python-only, Soroban, Anvil, Sepolia, Base-Sepolia}
Trials: ≥10 per cell (existing scripts use 5–20); report mean ± std
```

## 6. Deliverables

1. **Flat-line plot** — gas/fee vs T (on-chain) overlaid with PSolve ms vs T
   (off-chain). The constant-cost-verifier claim in one figure.
2. **Cost table** — Python `PVerify` (ms) vs on-chain gas + fee, per K, per
   venue. The direct smart-contract-vs-Python comparison.
3. **Latency table** — submit → finality per venue (testnets only).
4. **Security/cost frontier** — gas vs $2^{-K}$.
5. **Cross-chain table** — EVM gas vs Soroban CPU-instructions/fee.

## 7. Implementation checklist

### EVM (`contracts/quantum_verifier_evm`)
- [ ] Capture `receipt.gasUsed` per submission in `python/demo_eth.py`
      (tx hashes already printed).
- [ ] Read `effectiveGasPrice` from the same receipt → fee.
- [ ] Wall-clock around `cast send` → receipt → latency.
- [ ] Add `--benchmark` mode sweeping T and K → `bench/evm_results.json`
      (mirrors the `bench/stellar_results.json` placeholder).
- [ ] Optional: `gasleft()` instrumentation or a forge gas-snapshot profile
      for the per-phase breakdown.

### Soroban (`scripts/verify_sdk.py`)
- [ ] Wall-clock around `sign_and_submit` + `get_transaction`.
- [ ] Read actual consumed CPU instructions from simulation metadata
      (today's 30M `ResourceLeeway` is only a ceiling, not a measurement).
- [ ] Sweep T and K → `bench/stellar_results.json`.

### Python baseline
- [ ] `PVerify`-only timing loop (verify is the thing being replaced).
- [ ] Claim construction timing (serialization + Merkle path build).

### Reporting
- [ ] Extend `generate_latex_table.py` to join EVM + Soroban + Python JSONs
      into one comparison table.
- [ ] Plots: flat-line (deliverable 1), frontier (4), latency bars (3).

## 8. Methodological cautions

- **One variable at a time.** Hold lam/msg_bits/K fixed when sweeping T.
- **Anvil ≠ production.** Gas is meaningful; latency is not.
- **Testnet prices fluctuate.** Report fees in gas + native-token units, and
  convert to USD at measurement time with the price noted.
- **Warm vs cold storage.** First `submitAndVerify` against a puzzle may touch
  cold slots; report the steady-state (2nd+) verification gas per puzzle, or
  both numbers explicitly.
- **K default.** Keep K=8 as the reference point across all axes so tables
  align with the fixtures and prior measurements.
- **⚠️ Hard-fork repricing (measured 2026-10-13, Sepolia).** Deployment gas
  under the *current* Sepolia spec is **11,183,331** for this verifier — ~7×
  the 1.6M an anvil fork of the same chain reports. Per-verification gas is
  nearly unchanged (303,294 live vs 309,246 anvil), so the repricing hits
  one-time deploy, not per-claim cost. Consequences: (a) never trust
  fork/local gas numbers for *deployment* budgeting; (b) always set an
  explicit `--gas-limit` when deploying (2M and 5M both reverted silently,
  burning the full limit); (c) re-validate per-op gas after every network
  hard fork. `forge create` note: place `--rpc-url` **before**
  `--constructor-args` (the variadic swallows trailing flags).

## 9. First live-network results (Sepolia, 2026-10-13)

Venue: chain 11155111 via Alchemy; verifier
`0x70bA6106ab8624e286aD1D6232E9d43E391823e5` (immutable, free mode); solver
wallet `0x463b6e48dEC519D1229bF3D152a1c3B93282B144`; K=8; claim 4,096 B.
Raw rows: `contracts/quantum_verifier_evm/bench/evm_results.json`.

| op | gas | fee (ETH) | verdict |
|---|---|---|---|
| registerPuzzle | 245,056 | 2.9e-7 | puzzle 1 registered |
| verify honest K=8 | 303,294 | 3.6e-7 | **VERIFIED (s=1)** |
| verify cheat (s flipped) | 299,967 | 3.6e-7 | REJECTED reason 4 |
| verify unknown puzzle | 283,544 | 3.4e-7 | REJECTED reason 0 |

Cross-venue consistency: live K=8 gas (303,294) matches the Anvil golden-vector
measurement (309,246) within ~2%. Latency (22–72 s submit→receipt) is polluted
by manual keystore-password entry and is an upper bound only.

Demo usage (live network):

```sh
export PATH="$HOME/.foundry/bin:$PATH" CAST_PASSWORD=...   # keystore password
uv run python python/demo_eth.py --spot-checks 8 \
  --rpc-url $ETH_SEPOLIA_RPC --account base-sep \
  --verifier 0x70bA...823e5 --benchmark
```

Keys live in a local cast keystore (`~/.foundry/keystores/base-sep`); the raw
key never enters the repo. Testnet wallet: `0x463b6e48…B144`.
