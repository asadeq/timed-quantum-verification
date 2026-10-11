# Wire Format Specification — Quantum Verification Soroban Contract

> Single source of truth for the byte layout used by the Python off-chain
> tooling ([`scripts/serialize.py`](scripts/serialize.py)) and the Rust
> on-chain verifier (`contracts/quantum_verifier/src/types.rs`). Any
> change to one side must be mirrored in the other and in this file.

## Conventions

- All multi-byte integers are **big-endian u32** unless noted otherwise.
- Single-byte fields are u8.
- All Yao per-wire key material is **BytesN<16>** (128 bits), matching
  [`yao_helpers.KEY_LEN`](Quantum_vertification_artifact/timelock_puzzle/yao_helpers.py).
- SHA-256 hashes are **BytesN<32>**.
- All lists are length-prefixed with a u32 BE count.

## Structures

### `CircuitSpec` — immutable, set at `PSetup`

```
u32  lam
u32  msg_bits
u32  T
u8   sha256_circuit       (0 = xor_mixing, 1 = sha256)
```

Total: 13 bytes.

The contract stores `SHA-256(spec_bytes)` as `circuit_hash`.

### `PuzzleMeta` — public per-puzzle metadata

```
BytesN<32>  circuit_hash       (SHA-256 of CircuitSpec)
BytesN<32>  pk_commitment      (SHA-256 of the generator's pk dict)
u32         fee                (per-verify fee in stroops)
```

Total: 68 bytes.

### `Puzzle` — per-instance, off-chain PGen output

```
u32                 r_len
Bytes               r                       (Goldreich-Levin mask)
u8                  r_dot_m_xor_s           (the published commitment)

u32                 non_reusable_len
u32[]               non_reusable            (gate ids, sorted ascending)

u32                 tables_len              (= non_reusable_len * 4)
BytesN<16>[]        tables_flat             (4 ciphertexts per gate, flattened
                                             row-major: (a,b) = (0,0),(0,1),(1,0),(1,1))

u32                 sealed_boundary_len
(u32, BytesN<16>)[] sealed_boundary         (wire_id, ciphertext), sorted by wire_id

u32                 out_perm_len
(u32, u8)[]         out_perm                (wire_id, perm_bit), sorted by wire_id
```

Note: `m` is **not** in the puzzle — it is a generator secret. The
contract only needs `r` and `r_dot_m_xor_s` to run the Goldreich-Levin
check.

The `Puzzle` is **off-chain only** — it is never submitted to or stored by
the contract. Instead it is Merkle-ized (see "Puzzle Merkle tree" below)
and the root is registered as `puzzle_hash`.

## Puzzle Merkle tree (off-chain)

Built by `scripts/serialize.py::build_puzzle_merkle_tree` over the
serialized puzzle body:

```
header leaf   = SHA-256( r ‖ r_dot_m_xor_s_be32 ‖ non_reusable_be32… )
gate leaf(gi) = SHA-256( table[gi]_4×16B ‖ gi_be32 )
internal      = SHA-256( left ‖ right )        (odd count: last pairs with itself)
```

The root is what `register_puzzle` stores as `puzzle_hash`. Each claim
carries a Merkle path (sibling, is_left) from each leaf it needs up to
that root, so the on-chain verifier can authenticate the header and the
spot-checked tables without ever seeing the puzzle body.

### `Claim` — per-call, the solver's submission

```
Claim {
  header: ClaimHeader
  spot_checks: SpotCheckProof[]     (K = 8 recommended; first K gate ids)
  y_bits: u32[]                     (LSB-first circuit-output bits, 0/1)
  s_claim: u32                      (the bit the solver claims)
}

ClaimHeader {
  r: Bytes                          (Goldreich-Levin mask)
  r_dot_m_xor_s: u32                (the published commitment)
  non_reusable: u32[]               (sorted gate ids)
  merkle_path: (BytesN<32>, bool)[] (header leaf → puzzle_hash)
}

SpotCheckProof {
  gate_index: u32                   (must appear in header.non_reusable)
  k_l, k_r, k_o: BytesN<16>         (Yao input keys + claimed output key)
  table: (BytesN<16>, BytesN<16>,
          BytesN<16>, BytesN<16>)   (row-major ct for (a,b)=(00,01,10,11))
  merkle_path: (BytesN<32>, bool)[] (gate leaf → puzzle_hash)
}
```

On-chain checks, in order (`submit_and_verify` returns false + a
`rejected` event with the reason code on failure):

1. header Merkle path resolves to the registered `puzzle_hash` (reason 1)
2. every spot-check's Merkle path resolves to `puzzle_hash` (reason 2)
3. for each spot-check, `a = select_bit(k_l)`, `b = select_bit(k_r)`,
   `k_o == table[a*2+b] ⊕ pad(k_l, k_r, gate_index)` where
   `pad = SHA-256(k_l ‖ k_r ‖ gate_index_be64)[:16]` (reason 3)
4. `gf2(r, y) ⊕ s_claim == r_dot_m_xor_s` (reason 4)

## Golden vectors

Sizes for `lam=128, msg_bits=128` (640 non-reusable gates, 128-bit y):

| Structure | Size (bytes) | Notes |
|---|---|---|
| `spec_bytes`   | 13     | fixed at PSetup |
| `meta_bytes`   | 68     | commitment only |
| `puzzle_bytes` | 49 317 | **off-chain only** |
| `claim_bytes` (K=1) | 3 621 | measured via `serialize_claim` |
| `claim_bytes` (K=8) | 6 771 | measured via `serialize_claim` |
| `claim_bytes` (K=32) | 17 571 | measured via `serialize_claim` |

(Merkle depth is 10 for 641 leaves. Earlier hand-written estimates of
~3 509 / ~27 700 were wrong — the per-gate paths are 33 B each, so K=8 adds
only ~8 × 470 B over K=1. The sizes above are constant in T.)

The EVM verifier (`contracts/quantum_verifier_evm`) uses a **v2 claim layout**
(bitmap non-reusable header, u8 committed bits) documented in
[`contracts/quantum_verifier_evm/docs/WIRE_FORMAT_EVM.md`](contracts/quantum_verifier_evm/docs/WIRE_FORMAT_EVM.md);
its `puzzle_hash` therefore differs from the Soroban one — compute each chain's
hash off-chain and register it on that chain.

## Length prefixes

All variable-length fields use **u32 BE** counts. The maximum length of
any single field is bounded by the puzzle / claim size, which is itself
bounded by Soroban's per-transaction input limit (~2 MB in practice).

## Versioning

This is **v1** of the format. Future versions will append a `version: u8`
prefix to `Claim` only — the puzzle structures are immutable once
registered.
