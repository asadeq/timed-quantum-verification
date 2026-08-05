# PRGC Yao Section — End-to-End Walkthrough

This note traces what happens at setup, PGen, and PSolve for the Yao (non-reusable) section of the PRGC garbled circuit implemented in `Quantum_vertification_artifact/timelock_puzzle/tlp_garbling2.py`.

## 1. Where the Yao section lives

`PSetup_Garble` does three things after the circuit is built and non-reusable gates have been identified:

1. **Generate a per-wire key pair** `(K_w^0, K_w^1)` for every wire that carries secret information: every InputB wire (because `m`/`z` are secret), every parent of a non-reusable gate, and every output of a non-reusable gate.
2. **Encrypt the truth table of every non-reusable gate** using those keys.
3. **Leave reusable gates alone** in CRGC form (already XOR-flipped by `get_flipped_circuit`).

That is the entire Yao section.

## 2. The Yao gate, concretely

A non-reusable gate stores 4 ciphertexts instead of plaintext truth-table bits. Each ciphertext is one bit. The encryption is a classic double-key scheme using SHA-256:

```
combined = K_l[li] XOR K_r[ri]
prf_byte = SHA-256(combined)[0]
ciphertext[li][ri] = (prf_byte >> 7) XOR truthTable[li][ri]
```

So:

- If the solver has the right pair of parent keys `(K_l[li], K_r[ri])`, they can recompute `(prf_byte >> 7)` and XOR with the ciphertext to recover the logical output bit.
- If the solver has the wrong pair, SHA-256 is a one-way function, so they learn nothing about the output.

The truth table itself has the logical (un-flipped) values because the PRGC mode passes non-reusable gates **through** `swap_left_parent` / `swap_right_parent` only when their parents carry a `base_flipped` flag — but those flags are zero for the wires that get Yao keys, so the logical bits survive unchanged.

## 3. What PGen hands the solver

For each wire `w` in the Yao section:

- If `bit == 0`: send `K_w^0`.
- If `bit == 1`: send `K_w^1`.

Concretely in `encode_wire`:

```python
if wire_idx in yao_keys:
    k0, k1 = yao_keys[wire_idx]
    return k1 if bit else k0
```

So `encoded_inputB` is no longer `[False, False, True, ...]`. It is a list of 16-byte keys. The solver receives one key per InputB wire, and the key they receive encodes exactly the bit the generator chose.

## 4. Why this hides InputB

If the solver tries to read `m` directly, they see `K_w^0` or `K_w^1`. They cannot tell which value is "zero" and which is "one" without knowing the secret pairing — that pairing is what the garbled truth table plus the SHA-256 PRF enforce. So the solver cannot compute `r·m` in O(λ) anymore. The only way to learn `m` is to walk the non-reusable gates, which forces them through the sequential SHA-256 chain for T iterations.

## 5. What PSolve does at a non-reusable gate

The walker sees `left_val` and `right_val` as **bytes** (the keys that PGen delivered). The decrypt step is:

```python
K_left_0, K_left_1 = yao_keys[gate.leftParentID]
K_right_0, K_right_1 = yao_keys[gate.rightParentID]
li = 1 if left_val == K_left_1 else 0
ri = 1 if right_val == K_right_1 else 0
ciphertext_bit = gate.truthTable[li][ri]
out_bit = ungarble_bit(ciphertext_bit, left_val, right_val)
```

`li, ri` are recovered by equality comparison, not by index. Then:

- `gate.truthTable[li][ri]` is the single ciphertext bit.
- `ungarble_bit` recomputes `SHA-256(K_l[li] XOR K_r[ri])[0] >> 7` and XORs with the ciphertext to recover the logical output bit.

If the output wire itself is a Yao wire (it feeds another non-reusable gate), the evaluator stores `K_w^out_bit` for the next gate to consume. If the output wire feeds a reusable gate, it stores the wire-level bit (`out_bit XOR base_flipped[w]`) so the next reusable gate can read it normally.

## 6. The bridge between Yao and CRGC sections

The reuse/non-reuse closure ensures that if a gate is non-reusable, both its parents are Yao wires, and its output is either a Yao wire (if it feeds a non-reusable gate) or a wire-level bit (if it feeds a reusable gate). The `_to_wire_bit` helper handles the reverse direction:

```python
if isinstance(v, bytes):
    logical = 1 if v == yao_keys[w][1] else 0
    return logical ^ base_flipped[w]
```

So when a reusable gate has one parent in the Yao section, the walker infers the wire-level bit from the key, applies `base_flipped`, and feeds the reusable truth table as usual.

## 7. Summary

- **Setup**: for each non-reusable gate, encrypt the 4 truth-table entries with `SHA-256(K_l XOR K_r)`.
- **PGen**: for each secret wire, send the matching key. For each non-secret wire, send the CRGC-encoded bit.
- **PSolve**: at each non-reusable gate, decrypt using the delivered keys; at each reusable gate, use the flipped truth table; bridge the two by translating keys into wire-level bits as needed.

This is exactly the PRGC scheme from §2.5 of the CRGC paper, applied to the TLP construction.
