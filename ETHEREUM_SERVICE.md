# Quantum-Verification-as-a-Service on Ethereum

> Companion to [STELLAR_SERVICE.md](STELLAR_SERVICE.md). This is a **port plan**,
> not a commitment. It maps every piece of the current Soroban deployment onto an
> EVM equivalent, quantifies the cost delta with *measured* numbers, and lists the
> decisions that must be made before any code is written.

## TL;DR

The port is **small in code and large in economics**.

- **Code.** The on-chain verifier is ~250 lines of Rust across 6 files
  (`verifier.rs`, `merkle.rs`, `spot_check.rs`, `inner_product.rs`,
  `crypto_helpers.rs`, `store.rs`). A faithful Solidity port is ~300 lines.
  The off-chain TLP (`PSetup` / `PGen` / `PSolve`), the wire format in
  [SPEC.md](SPEC.md), and `scripts/serialize.py` are **chain-agnostic and do
  not change at all**.
- **Economics.** Soroban charges by CPU instructions and makes large calldata
  nearly free. The EVM charges by gas, and after **EIP-7623** calldata is the
  dominant term. Measured on the current serializer: a K=8 claim is
  **6,771 bytes** → **~271 K gas of calldata** vs **~10 K gas of SHA-256**.
  The proof bytes cost ~27× the cryptography they prove.
- **Verdict.** On Ethereum **L1** a verification costs ~$5 at 5 gwei — roughly
  **1,000× the current Soroban cost** (0.01 XLM). On an **L2** (Base / Arbitrum)
  it lands at ~$0.001–0.01, within a small factor of Soroban. **If the goal is a
  cheap public service, the port only makes sense on an L2.** If the goal is
  ecosystem reach, or the Phase-4 ZK upgrade, Ethereum is the better home and
  the cost is the price of admission.

---

## 1. Scope — what changes, what doesn't

| Layer | Today (Soroban) | Ethereum | Effort |
|---|---|---|---|
| TLP off-chain (`PSetup`/`PGen`/`PSolve`) | Python | **unchanged** | none |
| Wire format ([SPEC.md](SPEC.md)) | canonical bytes | **unchanged** | none |
| `scripts/serialize.py` | builds puzzle + claim | **unchanged** layout, + calldata packer | small |
| Merkle tree construction | SHA-256, odd-node self-pair | **unchanged** | none |
| On-chain verifier | Rust → WASM | Solidity → EVM | **medium** |
| Puzzle registry | instance storage | `mapping(uint32 => PuzzleMeta)` | small |
| Auth | `Address::require_auth()` | `msg.sender` / `Ownable` | small |
| Payment | SAC `token.transfer` | native ETH **or** ERC-20 `transferFrom` | medium |
| Events | `env.events().publish` | `emit` | small |
| Submission client | `stellar-sdk` `ContractClient` | `web3.py` / `cast` | medium |
| Deploy | `stellar contract deploy` | `forge script --broadcast --verify` | small |
| Tests | `cargo test` + real WASM | `forge test` (fuzz + invariant) | medium |
| Cost model | CPU instructions | gas (calldata-dominated) | **the whole decision** |

**The key structural fact:** the on-chain verifier is a ~1 % subset of the
system. Everything expensive and interesting (the TLP, the garbling, the
partition, the witness) already runs off-chain and is chain-agnostic. The port
touches the smallest, simplest part of the codebase.

---

## 2. The cost model is the decision

### 2.1 Measured claim sizes

From `scripts/serialize.py::serialize_claim` with the real shapes
(`lam=128, msg_bits=128`, 640 non-reusable gates, Merkle depth 10):

| K | claim bytes | calldata @ 40 gas/B | calldata @ 16 gas/B |
|---|---|---|---|
| 1 | 3,621 | 144,840 | 57,936 |
| 4 | 4,971 | 198,840 | 79,536 |
| **8** | **6,771** | **270,840** | **108,336** |
| 16 | 10,371 | 414,840 | 165,936 |
| 32 | 17,571 | 702,840 | 281,136 |

> ⚠️ **`SPEC.md` is stale here.** Its golden-vector table claims
> `claim_bytes (K=8) ≈ 27 700`. The serializer produces **6,771 B**. The
> 27,700 figure is a hand-written estimate that predates the per-gate Merkle
> path design. Reconcile `SPEC.md` before using it for any cost planning.

### 2.2 Where the bytes go (K=8, Soroban layout)

| Component | Bytes | Share |
|---|---|---|
| `non_reusable` list (640 × u32) | 2,564 | **38 %** |
| 8 × spot-check (index + 3 keys + 4 cts + path) | 3,604 | 53 % |
| header Merkle path (10 × 33) | 334 | 5 % |
| `r` (128 B) | 132 | 2 % |
| `y_bits` (128 × u8) | 132 | 2 % |
| `s_claim` + length prefixes | 5 | — |

> The shipped EVM verifier drops the non-reusable gate list entirely
> (superseding §6.2's bitmap step: the puzzle tree only contains non-reusable
> leaves, so the gate-leaf Merkle proof is the membership proof), shrinking the
> claim to ~4.0 KB for K=8 — see
> [`contracts/quantum_verifier_evm/docs/WIRE_FORMAT_EVM.md`](contracts/quantum_verifier_evm/docs/WIRE_FORMAT_EVM.md).

### 2.3 Where the gas goes (K=8)

| Term | Gas | Notes |
|---|---|---|
| **Calldata** | **~248,000** | EIP-7623 floor: `10 × (zero + 4 × nonzero)` → 40 gas/nonzero byte; 6.9 KB claim (measured before the non-reusable list was dropped; the claim is now ~4.0 KB) |
| SHA-256 precompile | 10,080 | `60 + 12 × ⌈len/32⌉`; header leaf 1,080, 8 gate paths 6,720, `pad()` 672 |
| Decoder + XOR + GL | ~54,000 | membership is now the gate-leaf Merkle proof itself (no list/bitmap scan) |
| **Total per verification (measured)** | **312,010** | forge trace, `honest_k8` fixture (pre-list-removal contract) |

> **Measured, not estimated.** After implementation, the K=8 verification
> measures **312,010 gas** on the shipped contract
> (`contracts/quantum_verifier_evm`, golden-vector fixture `honest_k8`), and
> K=1 measures 103,812. The earlier ~350 K estimate included the O(K×N) scan
> the bitmap removes. Per-verification cost on L1 @ 5 gwei ≈ $1.6; on an L2
> ≈ $0.001–0.01.

**Calldata is ~77 % of the bill.** The verifier's actual cryptography is a
rounding error. This inverts the Soroban intuition entirely: on Soroban the
design goal was "minimise CPU"; on the EVM the design goal is
**"minimise bytes on the wire"**.

### 2.4 Cost comparison

| Venue | Cost per K=8 verification | vs. Soroban |
|---|---|---|
| Soroban (today) | 0.01 XLM ≈ $0.003 | 1× |
| Ethereum L1 @ 5 gwei, $3,000 ETH | ~$5.25 | ~1,700× |
| Ethereum L1 @ 1 gwei | ~$1.05 | ~350× |
| Base / Arbitrum | ~$0.001–0.01 | ~1–3× |
| **Groth16 on L1** (§7.2) | ~$0.40 @ 5 gwei | ~130× |

> Gas prices and ETH price move; treat these as order-of-magnitude. The
> *ratios* are the durable part.

---

## 3. Decision points

These must be settled before Phase 1. Recommendations in **bold**.

### D1 — Which chain?

| Option | For | Against |
|---|---|---|
| Ethereum L1 | Credibility, deepest liquidity, ZK verifier ecosystem | ~1,700× Soroban cost; unusable for a per-call service |
| **Base / Arbitrum One** | Cheap, mature, USDC-native, big ecosystem | L2 bridge/sequencer assumptions |
| Arbitrum **Stylus** | Rust → WASM: reuses `crypto_helpers.rs` etc. almost verbatim | Smaller ecosystem; still pays calldata; ink gas model |

**Recommendation: Base (or Arbitrum One) for v1, with L1 as a "premium /
settlement" tier later.** If the team's priority is *reusing the Rust code*
rather than reaching the EVM ecosystem, Stylus is a genuinely strong
alternative and should be spiked in Phase 0.

### D2 — Which language?

**Recommendation: Solidity 0.8.x + Foundry.** Vyper is viable but has a smaller
auditor pool; Yul/Huff is premature optimisation given calldata dominates.
There is no production-grade Rust → EVM compiler, so "keep the Rust" means
Stylus (D1), not Solidity.

### D3 — Calldata encoding?

**Recommendation: keep the packed wire format from [SPEC.md](SPEC.md) and
hand-decode it.** ABI-encoding `Claim` as a struct with nested dynamic arrays
adds offsets, length words and 32-byte padding to every field — roughly 2–3×
the bytes, i.e. 2–3× the cost. The packed format is already frozen and already
has golden vectors.

### D4 — Payment?

| Option | Notes |
|---|---|
| Native ETH (`msg.value`) | Simplest; no allowance dance; needs CEI + reentrancy guard on `withdraw` |
| **ERC-20 (USDC)** | Matches the current SAC design; needs `transferFrom` + allowance UX; use `SafeERC20` |
| ERC-4337 paymaster | Users pay in USDC without holding ETH — best UX for a paid service |

**Recommendation: ERC-20 (USDC) with `SafeERC20`, plus an ERC-4337 paymaster
later.** Keep the "free mode" escape hatch (`fee == 0` or token unset) that the
current contract has — it is what makes the Testnet demo work.

### D5 — Upgradeability?

**Recommendation: immutable.** This matches the existing decision ("verifier is
read-only after deploy; pin the WASM hash via `contractmeta`"). On Ethereum the
equivalent is: verify source on Etherscan + Sourcify, publish the bytecode hash,
and deploy via **CREATE2** so the address is identical on every chain. If a bug
is found, deploy a v2 and let the registry point at it — do not add a proxy to a
cryptographic verifier.

### D6 — Claim size reduction?

**Recommendation: yes, do it before deploying.** See §6.2 — there is ~2.6 KB
(≈ 105 K gas, ~39 % of the bill) available for the taking.

---

## 4. Contract design

### 4.1 Interface (1:1 with the Soroban contract)

```solidity
contract QuantumVerifier {
    struct PuzzleMeta {
        bytes32 circuitHash;
        bytes32 pkCommitment;
        bytes32 puzzleHash;
        uint32  fee;
    }

    address public immutable admin;
    address public immutable paymentToken;   // address(0) => free mode
    uint256 public feePerVerify;
    uint256 public totalCollected;
    uint32  public puzzleCount;
    mapping(uint32 => PuzzleMeta) public puzzleMeta;

    event PuzzleRegistered(uint32 indexed puzzleId, uint32 fee);
    event Verified(uint32 indexed puzzleId, address indexed solver, bytes32 claimHash, uint8 s);
    event Rejected(uint32 indexed puzzleId, address indexed solver, uint8 reason);

    error NotAdmin();
    error PuzzleNotFound(uint32 puzzleId);
    error ClaimRejected(uint8 reason);   // 1..4, same codes as today

    function registerPuzzle(bytes32 circuitHash, bytes32 pkCommitment,
                            bytes32 puzzleHash, uint32 fee) external returns (uint32);

    function submitAndVerify(uint32 puzzleId, bytes calldata claim) external payable returns (bool);

    function withdraw(address to) external;
}
```

Note `submitAndVerify` takes `bytes calldata` — the packed wire format — not a
struct. That is D3.

### 4.2 The decoder (the only genuinely new component)

A calldata cursor with explicit bounds checks. This is where the port's risk
concentrates:

```solidity
library Cursor {
    struct C { uint256 off; uint256 end; }

    function u32(C memory c) internal pure returns (uint32 v) {
        require(c.off + 4 <= c.end, "truncated");
        assembly { v := shr(224, calldataload(c.off)) }
        c.off += 4;
    }

    function take(C memory c, uint256 n) internal pure returns (uint256 off) {
        require(c.off + n <= c.end, "truncated");
        off = c.off;
        c.off += n;
    }
}
```

Rules for this file:
- **Every** read is bounds-checked. Solidity 0.8's overflow checks do not apply
  inside `assembly`, and `calldataload` past the end silently returns zero.
- No unbounded loops. `K` is caller-controlled → cap it (`require(K <= MAX_K)`).
- Fuzz it hard (§8) and differential-test it against `serialize.py`.

### 4.3 SHA-256

Solidity's builtin `sha256(bytes memory)` compiles to a `staticcall` to the
precompile at `0x02`. For the 2,692-byte header preimage, prefer an assembly
`staticcall` that points **directly at calldata** to avoid a memory copy:

```solidity
function sha256Calldata(uint256 off, uint256 len) internal view returns (bytes32 h) {
    assembly {
        let ptr := mload(0x40)
        calldatacopy(ptr, off, len)
        if iszero(staticcall(gas(), 0x02, ptr, len, ptr, 32)) { revert(0, 0) }
        h := mload(ptr)
    }
}
```

### 4.4 Storage

`mapping(uint32 => PuzzleMeta)` instead of Soroban instance storage. One cold
`SSTORE` per slot on registration (~20 K gas each, 3 slots) — a one-time cost,
irrelevant next to the per-call calldata.

### 4.5 Payment & reentrancy

- Pull the fee **before** verification (matches current behaviour), using
  checks-effects-interactions.
- `withdraw` sends ETH → use a `nonReentrant` guard **and** prefer a
  pull-payment pattern (`mapping(address => uint256) pendingWithdrawals`) if
  native ETH is used. With ERC-20 the reentrancy surface is smaller but
  `SafeERC20` is still mandatory (non-standard return values, fee-on-transfer
  tokens).
- Guard against fee-on-transfer tokens by measuring the balance delta rather
  than trusting `fee`.

---

## 5. What does *not* change

Worth stating explicitly, because it is the reason this port is cheap:

- `PSetup` / `PGen` / `PSolve` — pure Python, no chain awareness.
- The Merkle tree construction (`build_puzzle_merkle_tree`) — SHA-256 over
  bytes, identical on both chains.
- The `puzzle_hash` — a SHA-256 root. **The same registered puzzle is valid on
  both chains.** This enables the dual-chain path in §9.
- The golden vectors in [SPEC.md](SPEC.md) — still valid.
- The claim semantics and the four rejection reasons (1 = header Merkle,
  2 = gate Merkle, 3 = spot-check, 4 = Goldreich-Levin).

---

## 6. Free wins available during the port

### 6.1 Fix the O(K × N) membership scan

`spot_check.rs` currently does, per spot check:

```rust
let pos = non_reusable.iter().position(|x| x == sc.gate_index);
```

That is a linear scan over 640 entries, 8 times. On Soroban it is cheap; on the
EVM it is ~50 K gas — **comparable to the entire calldata cost**. Both lists are
sorted, so replace it with either:
- a binary search (10 steps), or
- a single merged pass over `non_reusable` and the (sorted) spot-check indices.

### 6.2 Shrink the claim

| Change | Saves | Cost |
|---|---|---|
| ~~Commit to a **bitmap** of non-reusable gates in the header leaf instead of the full list~~ | ~2,484 B (~99 K gas) | shipped, then **superseded**: the list is dropped entirely — the tree only contains non-reusable leaves, so the gate-leaf Merkle proof is the membership proof and the claim is constant in T |
| Pack `y_bits` as bytes instead of `u32[]` | 112 B (~4.5 K gas) | trivial |
| Merkle **multiproof** across the K spot checks (share the top ~3 levels) | ~768 B (~31 K gas) | moderate |
| Drop `r` from the claim (it is already committed in the header leaf) | 132 B | needs a re-derivation path |

The list removal (beyond the bitmap step) makes the claim constant in T. It is
the highest-value optimisation and it is worth doing **before** the first
Ethereum deployment,
because it is a wire-format change and those are cheapest to make once.

### 6.3 Fix the duplicated spot-check

`spot_check.rs::verify_spot_check` computes `pad()` twice and repeats the
comparison three times (a copy-paste artifact). Harmless, but it is 2 wasted
SHA-256 calls per spot check on Soroban. Do not port the duplication.

---

## 7. Two strategic options Ethereum unlocks

### 7.1 Account abstraction

An ERC-4337 paymaster lets a solver pay in USDC without holding ETH, and lets
the service sponsor gas for onboarding. This is a real UX advantage over the
current SAC flow and is worth designing in from the start (it changes nothing
about the verifier itself).

### 7.2 ZK — the actual reason to be on Ethereum

Phase 4 step 18 of [STELLAR_SERVICE.md](STELLAR_SERVICE.md) proposes replacing
the explicit Merkle proof with a Halo2/Plonk proof of the whole quantum run.
That upgrade is **far more natural on Ethereum than on Soroban**:

- Groth16 verifiers are a solved, audited, commodity component on the EVM
  (~250 K gas, ~256 B proof). A Groth16 proof is *cheaper on L1* than the
  current 6.8 KB Merkle claim, **and** it removes the "the shadow is genuinely
  classical" assumption.
- Halo2 / Plonk verifiers exist for the EVM, and **EIP-2537** (BLS12-381
  precompiles, live since Prague) makes pairing checks cheap enough to be
  practical.
- `gnark` (Go) and `snarkjs` (JS) both emit Solidity verifiers directly.

So the honest framing is: **the Merkle verifier is a port; the ZK verifier is a
rewrite that Ethereum makes possible.** If ZK is on the roadmap, Ethereum is the
right target and the calldata cost is a transitional problem.

---

## 8. Testing & tooling plan

| Concern | Soroban today | Ethereum |
|---|---|---|
| Framework | `cargo test` + real WASM | **Foundry** (`forge test`) |
| Integration test | `tests/integration_register.rs` | `test/IntegrationRegister.t.sol` |
| Cross-language parity | `tests/pad_bisect.rs` (Python bytes → Rust `pad()`) | `test/PadBisect.t.sol` reading the same JSON fixtures via `vm.readFile` |
| Differential test | 50 puzzles × `T ∈ {1..4,10,100}` | same, Python reference vs. Solidity verdicts |
| Anti-cheat | flipped `k_o`, flipped `s_claim`, wrong leaf | same three cases |
| Budget check | CPU instructions | `forge snapshot` (gas per test) |
| Coverage | — | `forge coverage` |
| Fuzzing | — | `forge test --fuzz-runs 10000` on the decoder + spot-check |
| Invariants | — | fee accounting (`totalCollected == Σ fees`) |

**The parity tests are the highest-value item.** The `pad_bisect` test is what
caught the `clone_from_slice` direction bug on the Rust side; the Solidity
decoder is a strictly larger surface for exactly that class of bug. Keep the
Python-generated fixtures and feed them to both implementations.

---

## 9. Off-chain changes

| File | Change |
|---|---|
| `scripts/serialize.py` | **No layout change.** Add `pack_calldata(claim) -> bytes` (it is already `serialize_claim`). |
| `scripts/verify_eth.py` | **New.** `web3.py` + `eth-account`: build tx, `estimate_gas`, send, decode `Verified` / `Rejected` logs. |
| `scripts/deploy_eth.sh` | **New.** `forge script Deploy.s.sol --broadcast --verify --rpc-url $RPC`. |
| `scripts/test_verifier.py` | Port the negative cases to call the Solidity contract. |
| Key management | `cast wallet` / keystore / env var. No more `~/.config/stellar/identity/alice.toml`. |
| `bench/` | `stellar_results.json` → `evm_results.json` (gas per call, per K, per chain). |

The demo flow is otherwise identical: PSetup → PGen → PSolve → register →
submit → print events.

---

## 10. Phased plan

| Phase | Deliverable | Exit criterion |
|---|---|---|
| **0 — Spike** | Gas measurement on a Sepolia/Base-Sepolia fork with a stub verifier; Stylus feasibility check | Real gas number for K=8 within 20 % of the §2.3 estimate; D1–D6 decided |
| **1 — Types + decoder** | `Cursor`, `Claim` decoding, golden-vector parity tests | Python bytes → Solidity structs, byte-for-byte, for all `T ∈ {1,2,4}` |
| **2 — Verifier core** | `merkle.sol`, `spotCheck.sol`, `innerProduct.sol` | `forge test` parity: 50 puzzles × `T ∈ {1..4,10,100}` agree with Python |
| **3 — Registry + payment** | storage, auth, USDC/ETH fee, events, `withdraw` | Integration test: register → claim → `Verified`; flipped `s_claim` → `Rejected(4)` |
| **4 — Off-chain + deploy** | `verify_eth.py`, `deploy_eth.sh`, Sepolia demo | End-to-end round-trip on a public testnet |
| **5 — Optimise + document** | bitmap header, packed `y_bits`, multiproof, gas snapshot | `evm_results.json`; cost table in this doc updated with measured values |
| **6 — (optional) ZK** | Groth16/Halo2 verifier | Proof verifies on-chain; cost ≤ Merkle path |

Phases 1–4 are a **port**. Phase 6 is a **rewrite** and should be scoped
separately.

---

## 11. Effort estimate

| Workstream | Estimate |
|---|---|
| Solidity verifier + decoder | 3–5 days |
| Foundry test suite (incl. parity + fuzz) | 3–4 days |
| Off-chain client + deploy scripts | 2 days |
| Gas optimisation (bitmap, packing) | 2 days |
| Docs + cost benchmark | 1 day |
| **Total (Phases 1–5)** | **~2–3 weeks** for one engineer familiar with both stacks |
| Phase 6 (ZK) | **weeks–months**; a separate project |

The estimate is dominated by *testing*, not by writing the contract. The
contract is a mechanical translation of code that already exists and is already
correct.

---

## 12. What you gain, what you lose

**Gain**
- Access to the EVM ecosystem: wallets, tooling, auditors, hiring pool.
- L2 economics that are within a small factor of Soroban.
- **A credible path to the ZK upgrade** (§7.2) — the strongest technical argument.
- Account abstraction / paymasters for a much better payment UX.
- Foundry's fuzzing and invariant testing, which the current Rust suite lacks.

**Lose**
- **Sub-cent L1 fees.** This is the big one. The current design's headline claim
  ("sub-cent regardless of puzzle size") does not survive on L1.
- 5-second finality (L1 is ~12 s; L2s are fast again).
- Toolchain unity — the Rust crate currently serves as WASM, CLI and library.
- Cheap calldata, which the whole design leans on.

**Unchanged**
- The cryptography, the wire format, the off-chain work, the security model,
  the four rejection reasons.

---

## 13. Dual-chain migration path

Because `puzzle_hash` is just a SHA-256 root over chain-agnostic bytes:

1. Register the **same** `puzzle_hash` on both the Soroban contract and the EVM
   contract.
2. The same `Claim` bytes are valid on both — only the submission encoding
   differs (`scval` vs. calldata).
3. Emit `claim_hash` in the `Verified` event on both chains, so a verification
   performed on chain A can be *referenced* on chain B without re-verifying.

This means the port does not have to be a migration. It can be an **addition**:
keep Soroban as the cheap tier, add an L2 deployment for ecosystem reach, and
let the same off-chain artifacts serve both.

---

## 14. Open questions

1. **`SPEC.md` is wrong about claim size.** K=8 is 6,771 B, not ~27,700 B.
   Reconcile before any cost planning. (The K=1 figure, ~3,509 B, is close to
   the measured 3,621 B.)
2. **Is the goal reach or cost?** If cost, an L2 is mandatory and the answer is
   "Base". If reach, L1 + ZK is the coherent long-term answer.
3. **Is Stylus acceptable?** It would let the existing Rust verifier ship almost
   unchanged. Worth a one-day spike before committing to Solidity.
4. **Does the wire-format change break the paper's artifact?** The bitmap header
   shipped, and the non-reusable list was then dropped entirely (claim constant
   in T). The wire format
   is referenced by the CCS submission; each format revision needs a note in
   [SPEC.md](SPEC.md) and possibly in the artifact.
5. **Who audits the decoder?** The cryptography is simple and already reviewed;
   the hand-rolled calldata parser is the new risk and is the thing an auditor
   should focus on.
