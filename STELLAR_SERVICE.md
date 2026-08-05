# Quantum-Verification-as-a-Service on Stellar / Soroban

> Companion design doc for [README.md](README.md). Captures the plan to ship
> the PRGC TLP4 verifier as a public Soroban smart contract so the
> verification step can be paid for and observed on-chain. Cross-references
> the work in [Quantum_vertification_artifact/](Quantum_vertification_artifact/)
> and the Python reference in
> [timelock_puzzle/tlp_garbling.py](timelock_puzzle/tlp_garbling.py).

## TL;DR

The contract does **not** re-solve the TLP. The TLP's time-lock is a
**one-time cost paid by the solver** — once the solver has done the T
sequential SHA-256 steps and produced a candidate `y`, the verifier only
needs to **(a) verify the quantum run via a Merkle proof and (b) spot-check
a handful of the solver's TLP gate-decryptions to confirm they really did
the work**. The on-chain work is a constant amount of SHA-256 over a few
KB of proof bytes — independent of T.

So the contract is `verify_claim(env, spec, puzzle, claim)`:

1. **Quantum-run check** — verify a Merkle proof over the classical
   description of the quantum execution (the "shadow"). ~6 SHA-256 calls.
2. **TLP spot-check** — pick K random non-reusable gates from the puzzle,
   ask the solver to provide the corresponding input keys + output key, and
   verify `output = xor_bytes(ct, pad(k_l, k_r, gi))` for each. ~K
   SHA-256 + K XORs (K ≈ 8).
3. **Linear post-processing** — compute `s = r·m ⊕ y·r` and check it
   equals the claimed `s`. One inner product, no hashes.

The contract emits a `Verified` event iff all three checks pass. The
**TLP becomes a credential**: the solver demonstrates they did the work
(via the spot-check) without re-doing it on-chain.

CPU budget per call: **≤ 200 K instructions, independent of T**. WASM
target: **≤ 8 KB**. Per-call fee: sub-cent regardless of puzzle size.

Why Stellar / Soroban over Ethereum:

- **SHA-256 of large calldata is essentially free** on Soroban (charged by
  CPU-instruction count, not by byte). Calldata on Ethereum L1 is 16 gas /
  byte — even a 16 KB Merkle proof would cost ~$1 before any work.
- **5 s finality** is fine for a paid service.
- **Sub-cent fees per call** keep the price of a single verification well
  under a cent at current rates.
- **Rust toolchain matches the verifier's natural language** — the same
  Rust crate that compiles to WASM also runs as a CLI / library for tests
  and for the off-chain PGen / PSolve.
- **Fee model matches the workload**: each verification is a self-contained
  WASM call charging the user exactly for the cycles used.

## Why not Ethereum

- Calldata cost is the killer. Even on L2 (1–4 gas/byte) the proof bytes
  dominate the cost, and you'd be tempted to push the proof off-chain via
  IPFS at which point Soroban gives you the same UX with less ceremony.
- No native Rust toolchain — you'd write Solidity and replicate the
  verifier there, with a separate test suite = more surface area for bugs
  in a cryptographic verifier.
- PQC story is the same on both chains, so neither L1 gives a future-proof
  advantage on the resistance side.

## Architecture

```
┌─────────────────┐                ┌─────────────────────┐
│  PSetup (once)  │                │  Quantum Hardware   │
│  off-chain      │                │  off-chain          │
└────────┬────────┘                └──────────┬──────────┘
         │ pk, C̃                              │ run + classical shadow
         ▼                                     ▼
┌─────────────────┐                ┌─────────────────────┐
│  PGen (per q)   │                │  Classical Recorder │
│  off-chain      │                │  Merkle-ize run     │
└────────┬────────┘                └──────────┬──────────┘
         │ puzzle Z                            │ (root, leaf, path)
         │                                     │
         └──────────────┬──────────────────────┘
                        ▼
              ┌─────────────────────┐
              │   Solver (off-chain)│
              │   • T × SHA-256     │  ← TLP time-lock
              │   • unseal K_unlock │
              │   • run Yao section │
              │   • get y           │
              │   • spot-check keys │
              └──────────┬──────────┘
                         │ (y, claimed_s, merkle_proof, spot_check)
                         ▼
              ┌─────────────────────┐
              │   Soroban contract  │
              │   • verify Merkle   │  ← ~6 SHA-256
              │   • spot-check K    │  ← ~10 gates
              │   • s = r·m ⊕ y·r   │  ← 1 inner product
              │   • emit Verified   │
              └─────────────────────┘
```

The TLP is still cryptographic: the puzzle is sealed, the solver **must**
do the T sequential SHA-256 steps to recover `y`, and the spot-check
ensures they couldn't have produced `y` without doing so. The verifier
just doesn't have to repeat the work.

## On-chain layout

```
contracts/quantum_verifier/
├── Cargo.toml
├── src/
│   ├── lib.rs                # re-exports
│   ├── verifier.rs           # verify_claim (entry point)
│   ├── merkle.rs             # Merkle proof verification
│   ├── spot_check.rs         # TLP spot-check (K random gate decrypts)
│   ├── inner_product.rs      # GF(2) inner product for s = r·m ⊕ y·r
│   ├── types.rs              # contract types (CircuitSpec, Puzzle, Claim)
│   ├── crypto_helpers.rs     # sha256, xor, pack_bits, etc.
│   ├── store.rs              # instance storage helpers (registry)
│   ├── events.rs             # Verified/Rejected events
│   └── test.rs               # unit tests against Python-generated fixtures
└── testdata/                 # JSON fixtures generated by Python for parity tests
```

A second contract (optional, can be merged into the same one for v1):

```
contracts/quantum_billing/
└── src/lib.rs                # pay-per-call, escrow, payout logic
```

## Existing pieces we reuse (already in this repo)

- [Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py](Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py)
  — all per-wire primitives (`pad`, `xor_bytes`, `select_bit`,
  `gen_key_with_select_bit`, `pack_bits`, `unlock_key`, `boundary_mask`).
  These port 1:1 to Rust as private helpers in `crypto_helpers.rs`.
- [Quantum_vertification_artifact/timelock_puzzle/prgc_partition.py](Quantum_vertification_artifact/timelock_puzzle/prgc_partition.py)
  — the **partition** itself runs off-chain and is serialized into the
  puzzle (the contract only needs the partition list + boundary-wire order
  to verify).
- [timelock_puzzle/tlp_garbling.py](timelock_puzzle/tlp_garbling.py) —
  the **full** `PSolve` algorithm runs off-chain. The on-chain verifier
  only needs a tiny subset (the spot-check).
- [Quantum_vertification_artifact/run_experiments.py](Quantum_vertification_artifact/run_experiments.py)
  — generate fixtures + golden vectors used by the contract's test suite.

## Steps (grouped into phases, each independently verifiable)

### Phase 1 — Spec & serialization (no contract yet)

1. **Define a canonical wire format** for the puzzle & claim in this doc's
   "Wire format" section below.
   - `CircuitSpec { lam, msg_bits, T, sha256_circuit }` — fixed at PSetup.
   - `PuzzleMeta { circuit_hash: BytesN<32>, pk_commitment: BytesN<32>, fee: u32 }` —
     what the user submits to identify which puzzle to verify.
   - `Claim { merkle_root, merkle_path, merkle_leaf, spot_check_indices,
     spot_check_keys, y_bits, s_claim }` — the on-chain submission.
2. **Write a Python `scripts/serialize.py`** that converts a
   `PythonGarbledTLP.PGen(...)` output + a `PSolve(...)` output into the
   canonical bytes used by the contract. This is the single source of
   truth for both Rust and Python.
3. **Write Rust `types.rs`** matching the same bytes layout, with
   `#[contracttype]` for `CircuitSpec`, `Bytes` for everything else, and
   length-prefixed fields (u32 BE or varint).
4. **Golden-vector test**: run `serialize.py` for `T ∈ {1..4}`, hash the
   result, commit the hash to this doc. Both the Python and Rust parsers
   must produce identical hashes.

### Phase 2 — Verifier core (no storage, no auth)

5. **Implement `crypto_helpers.rs`** — 1:1 ports of `pad`, `xor_bytes`,
   `pack_bits`, `select_bit`, `unlock_key`, `boundary_mask`. Use
   `env.crypto().sha256(&bytes)` as the SHA-256 host function. No state,
   no side-effects.
6. **Implement `merkle.rs::verify_merkle(leaf, path, root)`** — given a
   32-byte leaf and a list of `(sibling, is_left)` entries, hash the path
   and compare to the root. ~6 SHA-256 calls for a typical HHL shadow.
7. **Implement `spot_check.rs::verify_spot(puzzle, indices, keys)`** —
   for each (gate index, (k_l, k_r, k_o)) triple, look up the puzzle's
   `tables[gi]`, compute `a = select_bit(k_l); b = select_bit(k_r)`,
   check `k_o == xor_bytes(tables[gi][a][b], pad(k_l, k_r, gi))`. ~K
   SHA-256 + K XORs (K = 8 by default).
8. **Implement `inner_product.rs::gf2_inner_product(a, b)`** — popcount
   of `a AND b`, mod 2. Used to compute `r·m ⊕ y·r`.
9. **Implement `verifier.rs::verify_claim(env, spec, puzzle, claim) ->
   Result<bool, Error>`**:
   1. Verify the Merkle proof (call `merkle::verify_merkle`).
   2. Verify the spot-check (call `spot_check::verify_spot`).
   3. Compute `y_int = bits_to_int(claim.y_bits)`,
      `r_int = bits_to_int(puzzle.r)`, `m_int = bits_to_int(puzzle.m)`,
      and check `claim.s_claim == parity(r_int & m_int) ^ parity(r_int &
      y_int) ^ puzzle.r_dot_m_xor_s` (or equivalently
      `gf2_inner_product(r, m) ^ gf2_inner_product(r, y) ==
      puzzle.r_dot_m_xor_s ^ claim.s_claim` — pick the cleaner form).
   4. Return `Ok(true)` on all three passing, `Ok(false)` otherwise.
10. **Unit-test `verify_claim` against Python fixtures** — generate 50
    puzzles with random `(s, x, m, r)` and a real `PSolve` call, run the
    Rust verifier, assert `verify_claim` returns `true` for every honest
    solver + `false` for every flipped bit. Use `Env::default()` and
    `env.mock_all_auths()`.
11. **Add a `cost_estimate.rs` test** that runs `verify_claim` for
    `T ∈ {1..1000}` against the same fixtures, prints CPU-instruction
    count per call, and confirms it's **constant in T** (≤ 200 K
    instructions).

### Phase 3 — Storage + auth + payment

12. **Add `store.rs`** with the puzzle registry:
    - `puzzle_count: u32`, `circuit_hashes: Map<u32, BytesN<32>>`,
      `puzzle_meta: Map<u32, PuzzleMeta>`, `admin: Address`,
      `fee_per_verify: i128`.
    - `register_puzzle(env, spec, circuit_hash, pk_commitment, fee)` —
      admin-only, increases `puzzle_count`, stores entries, emits
      `PuzzleRegistered`.
    - `withdraw(env)` — admin can pull accumulated fees.
13. **Add the public entry point**
    `submit_and_verify(env, puzzle_id, puzzle, claim, payment_token: Address)`:
    - Caller `require_auth()`.
    - Pull `fee_per_verify` from the caller via the Stellar Asset Contract
      (SAC) or a configured token; revert if balance/allowance insufficient.
    - Run `verify_claim(...)`. On `Ok(true)` → emit `Verified`, return
      `Ok(true)`. On `Ok(false)` → emit `Rejected`, return `Ok(false)`.
      Either way keep the fee.
14. **Add `events.rs`** with `#[contractevent]` structs:
    - `PuzzleRegistered { puzzle_id, fee }`
    - `Verified { puzzle_id, solver, claim, hash_of_claim }`
    - `Rejected { puzzle_id, solver, reason }`
15. **Add `test.rs`** — full round-trip: admin registers a puzzle, solver
    pays fee, calls `submit_and_verify`, asserts `Verified` event in
    `e.events()` and contract balance increased.

### Phase 4 — Optional v2 features

16. **ZK-merkle** (optional) — replace the explicit Merkle proof with a
    Halo2 / Plonk proof that the entire quantum run was correct. Adds
    fixed cost (~100 K SHA-256-equivalent) but lets us drop the
    assumption that the shadow is genuinely "classical".
17. **Multi-puzzle batching** (optional) — let one transaction submit
    claims for K puzzles and pay a single fee. Reduces per-puzzle cost
    by amortizing the contract-call overhead.
18. **Spot-check K randomization** (optional) — currently K and the
    indices are chosen by the solver. In v2, the contract should pick
    them from `env.prng()` and the solver pre-signs a response to the
    deterministic challenge. Adds an extra round-trip but eliminates the
    solver's freedom to choose easy gates.

### Phase 5 — Build, deploy, demo

19. **Build**: `stellar contract build` →
    `target/wasm32v1-none/release/quantum_verifier.wasm`. Confirm
    `< 64 KB` (target: ≤ 8 KB).
20. **Deploy to Testnet**:
    `stellar contract deploy --wasm ... --alias quantum_verifier --source-account alice --network testnet`.
21. **CLI demo script** `scripts/demo.py`: spin up `TLP` in Python →
    `PGen` + `PSolve` → serialize → submit via `stellar contract invoke` →
    read `Verified` event → assert on-chain claim matches off-chain `s`.
22. **Benchmark**: `scripts/bench.py` — submit 100 verifications across
    `T ∈ {1..1000}`, record CPU-instruction cost and Stellar fee per
    call, write to `bench/stellar_results.json`. Confirm cost is
    constant in T.

## Relevant files

**To create:**

- `contracts/quantum_verifier/Cargo.toml`
- `contracts/quantum_verifier/src/lib.rs`
- `contracts/quantum_verifier/src/types.rs`
- `contracts/quantum_verifier/src/crypto_helpers.rs`
- `contracts/quantum_verifier/src/merkle.rs`
- `contracts/quantum_verifier/src/spot_check.rs`
- `contracts/quantum_verifier/src/inner_product.rs`
- `contracts/quantum_verifier/src/verifier.rs`
- `contracts/quantum_verifier/src/store.rs`
- `contracts/quantum_verifier/src/events.rs`
- `contracts/quantum_verifier/src/test.rs`
- `scripts/serialize.py` — Python side
- `scripts/demo.py` — end-to-end test
- `scripts/bench.py` — cost measurements
- `bench/stellar_results.json`

**To reuse (read-only):**

- [yao_helpers.py](Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py)
  — primitives to port to Rust
- [prgc_partition.py](Quantum_vertification_artifact/timelock_puzzle/prgc_partition.py)
  — runs off-chain; its output becomes part of the puzzle bytes
- [tlp_garbling.py](timelock_puzzle/tlp_garbling.py) — **full** `PSolve`
  runs off-chain. The on-chain verifier is a 1 % subset (the spot-check
  + Merkle proof + linear post-processing).
- [run_experiments.py](Quantum_vertification_artifact/run_experiments.py)
  — fixture generator for parity tests

## Wire format (initial draft — finalized in Phase 1)

```
CircuitSpec                          (fixed-size, all BE)
  u32  lam
  u32  msg_bits
  u32  T
  u8   sha256_circuit (0/1)

PuzzleMeta                           (fixed-size)
  BytesN<32>  circuit_hash
  BytesN<32>  pk_commitment
  u32         fee

Puzzle                                (per-instance, off-chain PGen output)
  BytesN<λ>     r                       (Goldreich-Levin mask)
  BytesN<msg>   m                       (the message commitment)
  u8            r_dot_m_xor_s          (the published commitment)
  u32           non_reusable_len
  u32[]         non_reusable            (gate ids, sorted)
  u32           tables_len
  (BytesN<16>[4]) tables[gi]            (4 ciphertexts per gate)
  u32           sealed_boundary_len
  (u32, BytesN<16>) sealed_boundary     (wire_id, ciphertext)
  u32           out_perm_len
  (u32, u8)   out_perm                  (wire_id, perm bit)

Claim                                (per-call, the solver's submission)
  BytesN<32>     merkle_root            (committed at puzzle registration)
  u32            merkle_path_len
  (BytesN<32>, bool)[] merkle_path      (sibling, is_left)
  BytesN<32>     merkle_leaf            (the run leaf being proven)
  u32            spot_check_len            (K = 8 by default)
  u32[]          spot_check_indices       (which non-reusable gates to check)
  (BytesN<16>, BytesN<16>, BytesN<16>)[] spot_check_keys
                                          (k_l, k_r, k_o per gate)
  u32            y_bits_len
  u8[]           y_bits                   (the y from off-chain PSolve)
  u8             s_claim                  (the bit the solver claims)
```

Length-prefixed fields use **u32 BE** (4 bytes). All key material is
**BytesN<16>** (128-bit Yao per-wire keys, matching `KEY_LEN` in
[`yao_helpers.py`](Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py)).

Note: the puzzle no longer ships `encoded_inputA`/`encoded_inputB` —
those are only needed to *run* the circuit, which the verifier no longer
does. The only parts of the puzzle the contract needs are the
non-reusable gate tables, the sealed boundary keys (for the spot-check),
and `out_perm` (to decode `y`).

## The spot-check construction

The spot-check is the heart of the new design. For each randomly chosen
non-reusable gate `gi`, the solver must provide:

- `k_l` — the left-parent's Yao key the solver actually used
- `k_r` — the right-parent's Yao key the solver actually used
- `k_o` — the output wire's Yao key the solver actually recovered

The contract then computes:

```
a = select_bit(k_l)                      # point-and-permute row
b = select_bit(k_r)
ct = tables[gi][a][b]                    # the garbled ciphertext
expected_k_o = xor_bytes(ct, pad(k_l, k_r, gi))
```

and checks `k_o == expected_k_o`. If this holds for K = 8 random gates,
the probability of a cheating solver (who skipped the T-step unseal) is
2⁻⁸ ≈ 0.4 %. With K = 16, it's 1.5 × 10⁻⁵ — well below any rational
attack budget.

The keys are deterministic given the solver's honest execution: once they
have `K_unlock` and the boundary keys, every gate's keys are determined
by the puzzle. So a cheating solver who didn't do the T sequential work
can't produce consistent keys for any K ≥ 1.

A small subtlety: the boundary keys for the spot-check are *sealed* in
the puzzle. The solver must have unsealed them (which requires the T
sequential SHA-256s) to produce valid `k_l`/`k_r` for the gates that
consume reusable outputs. The contract doesn't need to check this
explicitly — it falls out of the spot-check itself.

## Verification

1. **Parity tests** — for 50 random puzzles per `T ∈ {1..4, 10, 100}`,
   the Rust `verify_claim` and the Python `_evaluate_prgc + GF(2)
   post-processing` return identical verdicts. Run via `cargo test`.
2. **WASM size** —
   `wc -c target/wasm32v1-none/release/quantum_verifier.wasm` ≤ 64 KB;
   target ≤ 8 KB.
3. **CPU budget** — `cost_estimate.rs` reports ≤ 200 K CPU instructions
   per verify, **constant in T** (verified across T ∈ {1, 10, 100, 1000}).
4. **Anti-cheat** — for the same 50 puzzles, run `verify_claim` with a
   single bit of `k_o` flipped in the spot-check; assert `verify_claim`
   returns `false`. Repeat with one bit of `s_claim` flipped; assert
   `false`. Repeat with a wrong Merkle leaf; assert `false`.
5. **End-to-end Testnet deploy** — `stellar contract deploy` +
   `stellar contract invoke` round-trip succeeds; `Verified` event
   visible in `stellar events` CLI.
6. **Fee measurement** — at current network rates, each verification
   costs ≤ $0.0005; verified via `bench/stellar_results.json`. Confirmed
   constant in T.

## Decisions

- **Verifier is claim-check, not re-solve.** The TLP is a credential; the
  solver proves they did the work via the spot-check, not by re-doing it
  on-chain. This drops the per-call cost **100×** and removes the T-cap.
- **Single contract, not a contract-per-puzzle.** The puzzle spec is small
  (32-byte hash, a few ints); storing it in `Map<u32, ...>` keeps WASM small
  and lets users share code paths. Deploying N contracts would burn N × 50
  XLM (rent) per puzzle and balloon the WASM bytecode.
- **Verifier is read-only after deploy.** No `set_admin` / `upgrade` — pin
  the WASM hash via `contractmeta`, so users can verify the verifier by
  inspecting the contract ID on the Stellar Lab explorer.
- **Payout in a Stellar Asset Contract (SAC), not native XLM.** Lets the
  service charge in any token (USDC, BTC-via-bridge) without redeploying.
- **Solver picks the spot-check indices in v1.** Honest solvers will
  include genuinely random indices; a cheating solver can only choose
  easy gates, but the spot-check works on any non-reusable gate. v2
  (Phase 4 step 18) adds contract-driven randomness.
- **Phase 4 is optional.** v1 ships with solver-chosen spot-check indices
  and a plain SHA-256 Merkle proof. The ZK / randomization upgrades
  don't change the public interface.

## Further considerations

1. **CRGC vs PRGC verification.** CRGC puzzles have an order of magnitude
   smaller proof bytes and no SHA-256 chain — much cheaper to verify
   on-chain. Option A: only PRGC (simpler, single code path). Option B:
   dual mode (`verify_crgc` + `verify_prgc`) selected by `spec.mode`
   enum. **Recommendation: PRGC only for v1** (it's the cryptographic mode
   the paper advocates), add CRGC later if we need a cheap-test tier.
2. **Spot-check K.** Default K = 8 (≈ 0.4 % cheating probability). Higher
   K = more on-chain cost but better security. **Recommendation: K = 8
   for v1**, expose `K` as a per-puzzle parameter so high-value puzzles
   can use K = 32.
3. **Quantum-shadow format.** The Merkle tree commits to a classical
   description of the quantum execution. For HHL this is ~1 KB
   (rotation angles, measurement results). For Shor / Grover it would be
   larger but the same shape. **Recommendation: document the shadow
   format per supported algorithm in `contracts/quantum_verifier/
   shadow_formats.md`.**
4. **Verifier-as-a-library vs verifier-as-a-service.** Two ways to
   monetize: (a) keep the contract open and free, charge via the
   `fee_per_verify` token transfer; (b) gate the function behind
   `require_auth` of an authorized solver list. Option (a) is the
   "Quantum-as-a-Service" model this doc targets —
   **recommendation: go with (a)**.

## What changed vs the previous plan

- **Old plan:** re-execute the entire `PSolve` (T SHA-256 + Yao
  evaluation) on-chain for every verification. On-chain CPU scaled with
  T; cap T at 8–10.
- **New plan:** verify the solver's *claim* via a Merkle proof over the
  quantum run + a constant-size spot-check of the solver's TLP gate
  decryptions + a 1-bit inner-product check. On-chain CPU is constant
  in T; no T-cap.
- **Cost delta:** ~100× cheaper per call. WASM target drops from ≤ 20 KB
  to ≤ 8 KB. Verifier size drops from "port everything" to "port a
  1 % subset".
- **Security delta:** unchanged. The TLP is still cryptographic; the
  spot-check is the new on-chain witness that the solver did the T
  sequential work.
- **Public interface delta:** `verify_prgc(spec, proof)` →
  `verify_claim(spec, puzzle, claim)`. Cleaner names, smaller
  arguments.
