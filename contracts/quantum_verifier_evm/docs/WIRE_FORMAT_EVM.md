# EVM claim wire format (v1)

The claim submitted to `QuantumVerifier.submitAndVerify(uint32, bytes)` is
**packed, not ABI-encoded** — ABI struct encoding would add offset/length words
and 32-byte padding to every field, roughly tripling the calldata, and calldata
is ~77% of the verification bill (see
[`ETHEREUM_SERVICE.md`](../../ETHEREUM_SERVICE.md)).

All integers are big-endian. This is the format produced by
`python/gen_fixtures.py::serialize_claim` and decoded by
`src/lib/ClaimCodec.sol`.

```
u32            r_len
bytes          r                      (Goldreich-Levin mask)
u8             r_dot_m_xor_s          (0 or 1; >1 rejected)
u32            bitmap_len
bytes          bitmap                 (bit gi set => gate gi is non-reusable)
u32            header_path_count
(bytes32,u8)[] header_path            (sibling, is_left)
u32            K                      (spot-check count)
SpotCheck[K] {
    u32            gate_index
    bytes16        k_l
    bytes16        k_r
    bytes16        k_o
    bytes16[4]     table              (row-major (a,b)=(00,01,10,11))
    u32            path_count
    (bytes32,u8)[] path               (sibling, is_left)
}
u32            y_len
bytes          y                      (circuit output bits, LSB-first)
u8             s_claim                (0 or 1; >1 rejected)
```

## Merkle tree

Built off-chain by the puzzle generator; only the root (`puzzleHash`) is
registered on-chain.

```
header leaf   = SHA-256( r || r_dot_m_xor_s_be32 || bitmap )
gate leaf(gi) = SHA-256( table[gi]_4x16B || gi_be32 )
internal      = SHA-256( left || right )   (odd count: last pairs with itself)
```

Path entry `(sibling, is_left)`: `is_left = 1` means the sibling is the LEFT
child (the current node is the right child); the path byte must be 0 or 1.

## Differences from the Soroban format ([SPEC.md](../../SPEC.md))

| Field | Soroban | EVM | Why |
|---|---|---|---|
| non-reusable gates | `u32[]` (2,564 B for 640 gates) | **bitmap** (112 B) | ~99 K gas saved; O(1) membership |
| `r_dot_m_xor_s` | u32 | u8 | it is a bit |
| `s_claim` | u32 | u8 | it is a bit |
| `y_bits` | `u32[]` of bits | raw bytes | 112 B saved |

**Consequence:** the header leaf differs, so `puzzle_hash` differs from the
Soroban one. Compute each chain's hash off-chain and register it on that chain.
The claim bytes differ anyway (`scval` vs packed calldata).

## Canonical decoding rules (anti-malleability)

The decoder (`Cursor` + `ClaimCodec`) enforces, and a claim that violates any of
these reverts before any cryptographic check runs:

- every read is bounds-checked (`Truncated`), including inside `assembly`;
- booleans are canonical: path `is_left` and both committed bits must be 0 or 1;
- the claim region must be consumed exactly (`TrailingBytes`);
- caller-controlled lengths are capped: `r`/`y` ≤ 64 B, bitmap ≤ 512 B, K ≤ 64,
  path depth ≤ 64;
- `r` and `y` must have equal length (the Rust port silently truncated — that
  would let a solver choose how much of `r` is checked).

## Measured sizes and gas

Fixture: `lam = msg_bits = 128`, T = 1, 640 non-reusable gates, Merkle depth 10.

| K | claim bytes | total gas (measured, forge trace) |
|---|---|---|
| 1 | 3,744 | 103,812 |
| 8 | ~6,890 | 312,010 |

Reject paths cost less (they bail out early). The dominant term is calldata
(~40 gas per nonzero byte under EIP-7623).
