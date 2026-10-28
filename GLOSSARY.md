# Glossary

Terms and concepts used across the PV-CVQC protocol, the EVM verifier, and the
benchmark/commerce experiments. File and symbol links are relative to this
repository root.

## Protocol and roles

**PV-CVQC** — *Publicly Verifiable Confidential/Verifiable Quantum
Computation*. The scheme implemented in this repository: a quantum server
delegates-executes a client's circuit; anyone can verify the result without
re-running it, built from the CCY protocol garbling layers sealed behind a
time-lock puzzle. Entry point: [pv_cvqc.py](pv_cvqc.py).

**Client** — the party who owns the computation. Compiles the circuit,
garbles it into a TLP, registers the puzzle root on-chain and escrows a
bounty. In the commerce experiment, the account that calls `registerPuzzle`.

**Quantum server (solver, prover)** — the party who does the heavy work:
solves the time-lock (grinds the T sequential steps) and returns the output
plus a claim. Bound to its own address; paid the bounty on a verified claim.

**Admin** — deployer-level account of the `QuantumVerifier` contract. Sets
and withdraws service fees only; cannot touch puzzles or escrowed bounties
(those belong to puzzle owners).

**Attacker** — experiment role exercising the failure paths: front-running
replay (reason 1), double claim (reason 5), lying output (reason 4).

**Mahadev protocol** — interactive CVQC construction
([cvqc_protocol/mahadev_protocol.py](cvqc_protocol/mahadev_protocol.py)),
used as the conceptual reference: verifier sends random challenges; PV-CVQC
replaces the interactive challenges with non-interactive spot checks.

## Time-lock puzzle (TLP)

**TLP (time-lock puzzle)** — a puzzle whose solution requires *T* strictly
sequential steps, but whose correctness can be checked quickly. In this repo
the sequential work is SHA-256 chaining
([timelock_puzzle/](Quantum_vertification_artifact/timelock_puzzle)).

**T (μ)** — the time parameter: number of sequential SHA-256 steps the solver
must perform. Set from (or substituting for) the circuit depth. The on-chain
verification cost is independent of T; only the solver pays it.

**λ (`lam`)** — security parameter in bits (default 128); sizes wire keys and
the Goldreich–Levin mask.

**`msg_bits`** — size of the secret message hidden behind the puzzle
(default 128 bits). Drives the number of non-reusable gates (640 for 128
bits).

**PSetup_Garble / PGen / PSolve / PVerify** — the four protocol phases:
garbling setup, puzzle generation (client-side), solve (server-side), and
fast verification. See [PRGC_YAO_SECTION.md](PRGC_YAO_SECTION.md).

## Garbling (PRGC/Yao layer)

**Garbled circuit** — a circuit whose truth tables are encrypted under random
wire keys, so evaluating it reveals nothing about intermediate values.

**PRGC** — *Partially Reusable Garbled Circuit*: only a subset of gates is
garbled; the rest stay reusable (CRGC form). Fewer garbled gates = cheaper
setup.

**Non-reusable gates** — gates whose output keys cannot be re-derived without
doing the T sequential work. The only gates eligible for spot checks
(enforced on-chain by the bitmap check). Sorted list of 640 for the default
configuration.

**Wire keys (`k_l`, `k_r`, `k_o`)** — 16-byte random keys per wire. A spot
check reveals the left-parent key, right-parent key, and claimed output key
of one gate.

**Select bit** — the LSB of a wire key's first byte; picks which of the four
garbled table rows to decrypt (point-and-permute).

**Garbled table** — the 4 × 16-byte ciphertext block of a non-reusable gate,
committed via a Merkle gate leaf.

**pad** — the per-(gate,row) one-time pad: `SHA-256(k_l ‖ k_r ‖ gi_be64)[:16]`.
Rebinds the gate index so tables cannot be swapped between gates.

## Verification

**Spot check (K)** — one gate-opening check inside a claim: the solver
reveals a gate's table, its three wire keys, and a Merkle path; the contract
recomputes `k_o == table[select(k_l), select(k_r)] ⊕ pad`. K is chosen per
claim; faking all K checks has probability 2⁻ᴷ. Gate-level instance of the
cut-and-choose paradigm (Lindell–Pinkas); sampled result-checking in the
Freivalds/Blum sense. See [SPEC.md](SPEC.md) and
[WIRE_FORMAT_EVM.md](contracts/quantum_verifier_evm/docs/WIRE_FORMAT_EVM.md).

**K** — the number of spot checks in a claim. Protocol-level security dial
(cheat probability 2⁻ᴷ), not a chain concept; the chain only prices each
unit of K. Capped on-chain at `MAX_K = 64`.

**Claim** — the solver's packed submission (~4 KB at K=8): Goldreich–Levin
material, the non-reusable bitmap, K spot checks, and the output bits
(`y`) + claimed bit (`s_claim`).

**Goldreich–Levin (GL) check** — the inner-product binding
`gf2(r, y) ⊕ s_claim == r_dot_m_xor_s`: proves the solver's output bit
corresponds to the committed secret; a flipped output bit fails here
(reason 4).

**Merkle puzzle tree** — the off-chain commitment over the whole puzzle body:
one header leaf plus one leaf per non-reusable gate. Only the 32-byte root is
registered; claims authenticate slices via paths.

**Header leaf** — `SHA-256(r ‖ r_dot_m_xor_s ‖ bitmap ‖ solver_addr)`. The
trailing address binds the claim to the submitting account: a valid claim is
worthless from any other address (anti-front-running).

**Puzzle hash (`puzzleHash`)** — the Merkle root registered on-chain by the
client. Because the leaf binds the solver address, the root is computed for a
specific (puzzle, solver) pair.

## On-chain (EVM)

**QuantumVerifier** — the Solidity verifier
([contracts/quantum_verifier_evm/src/QuantumVerifier.sol](contracts/quantum_verifier_evm/src/QuantumVerifier.sol)).
Permissionless registration, atomic bounty settlement, admin-limited fees.

**`registerPuzzle`** — permissionless; caller becomes puzzle `owner`, escrows
the bounty, stores only the Merkle root.

**`submitAndVerify`** — one atomic transaction: fee collection (if any),
header path, K spot checks, GL check, bounty settlement. Returns false and
emits `Rejected(reason)` rather than reverting, so failures are auditable.

**Rejection reasons** — 0 unknown puzzle, 1 header path invalid (includes
wrong submitter), 2 gate path invalid, 3 Yao check or bitmap failure, 4
Goldreich–Levin failure, 5 bounty already claimed.

**Bounty (escrow)** — client-posted reward `B`, held by the contract and paid
to the first solver whose claim verifies, in the same transaction
(`BountyPaid`). Unclaimed bounties return to the owner via `reclaimBounty`.

**Free mode** — `feePerVerify = 0`: the only money flow is client escrow →
verified server. The mode used by all experiments.

**Solver binding** — the header-leaf address commitment above. Exists
because a bounty makes front-running profitable otherwise.

**Bitmap** — the 112-byte (default config) bit-array of non-reusable gate
indices, committed in the header leaf; O(1) membership replacing the older
O(K×N) list scan.

## Experiment and metrics

**Venue** — which chain a run targeted (`anvil`, `sepolia`); recorded in
every result row.

**K sweep / T sweep** — benchmarking one parameter while holding the other
fixed (`sweep_k.py`, `sweep_t.py`). K sweep: T=1, K ∈ {1,2,4,8,16}; T sweep:
K=8, T ∈ {1,10,25,50,100}.

**Honest vs cheat claim** — honest: genuine solve, expected `Verified`;
cheat: `s_claim` flipped, expected `Rejected(4)`. The gas of both is
recorded (cheating costs the same calldata and buys an auditable rejection).

**Gas** — EVM execution+calldata units. Verification gas is linear in K
(~30 K gas per extra spot check) and near-flat in T.

**Fee** — gas × effective gas price, reported in ETH. Figures quote fees at a
1 gwei reference gas price (`REF_GWEI` in `plot_paper.py`); live Sepolia
prices during the experiments ranged 0.0003–0.05 gwei, making measured fees
10⁻⁸–10⁻⁵ ETH.

**Latency** — wall-clock time from `cast send` to receipt (dominated by
block cadence, ~12 s on Sepolia), independent of T and K.

**Off-chain solve time** — measured `PSolve` duration (ms); grows with T.
Contrasted against flat on-chain cost to show the asymmetry.

**Bounty pricing (gas + margin)** — `B = (65,210 + 29,826·K)·gas_price +
margin_wei`: the client escrows the estimated verification gas plus a fixed
server margin. Constants are the Sepolia linear fit of honest-claim gas.

**Cheat EV** — a rational attacker's expected value per attempt:
`2⁻ᴷ·B − gas`. Negative for K above the crossover `log₂(B/gas)`; the
K-selection rule follows.

**Commerce cycle** — one full loop of the experiment
([experiment_commerce.py](contracts/quantum_verifier_evm/python/experiment_commerce.py)):
register + escrow → solve → submit → payout, plus the four attack controls.

**Ledgers** — `contracts/quantum_verifier_evm/bench/evm_results.json`
(benchmark sweeps: gas/fee/latency per tx) and
`contracts/quantum_verifier_evm/bench/commerce_ledger.json`
(commerce cycles: balances, events, profit). Paper figures render from these
via `plot_paper.py`.
