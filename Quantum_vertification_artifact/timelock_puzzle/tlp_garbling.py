"""
Complete Python-based TLP with Circuit Garbling (v4)

Fix: the boundary keys are delivered ENCRYPTED under an unlock key
    K_unlock = SHA256( pack( wire-level values of all boundary wires ) )
The wire-level value of the chain-output boundary wires is only known
after evaluating the whole reusable (sequential) section, so the Yao
section stays sealed until the sequential work is done. In the random
oracle model, obtaining any valid boundary key requires querying SHA-256
on the true chain output, i.e. performing the T sequential evaluations —
the same assumption the TLP itself rests on. The generator knows all
plaintext wire values (it owns the inputs), so it derives K_unlock at PGen
time non-interactively.

Retained from v3 (reviewer fixes):
1. Per-puzzle freshness: Yao keys AND encrypted tables of the non-reusable
   section are generated fresh in every PGen (no cross-puzzle key reuse).
2. Flip bookkeeping fixed: reusable-gate output flips are recorded in
   wire_flip as they are applied.
3. Solver is pk-free: point-and-permute select bits on every Yao key.
4. No ancestor closure: non-reusable = gates downstream of InputB / leaked
   InputA wires, plus final output gates.

"""

import hashlib
import secrets
import copy
import math
from typing import Tuple, List, Union, Set, Dict

from timelock_puzzle.tlp_circuit_builder import create_tlp_unrolled_circuit
from timelock_puzzle.sequential_functions import SequentialFunction, create_sequential_function_for_circuit
from timelock_puzzle.prgc_partition import find_non_reusable_gates
from crgc_garbled_circuits import *
from crgc_garbled_circuits.circuit_flipper import get_flipped_circuit
from crgc_garbled_circuits.circuit_evaluator import evaluate_transformed_circuit
from crgc_garbled_circuits.helper_functions import (
    swap_left_parent,
    swap_right_parent,
    flip_table,
)
from yao_helpers import (
    KEY_LEN,
    gen_key_with_select_bit,
    select_bit,
    pad,
    xor_bytes,
    pack_bits,
    unlock_key,
    boundary_mask,
)


class PythonGarbledTLP:
    """
    Time-Lock Puzzle from Lattices (Agrawal et al. 2024) - Construction 4.1

    Circuit C(b, x, m, z, i):
      - If i = T+1: return m if b=0, else x⊕z
      - Otherwise: return (b, f(x), m, z, i+1)

    - PSetup(1^λ, T): Returns pp = (C̃, pk) where C̃ ← rGC.Garble(1^λ, C_T)
    - PGen(pp, s): Sample x,m,r ← {0,1}^λ, encode x̃ ← rGC.Enc(pk, (0,x,m,0^λ,1)),
                   return Z = (x̃, r, r·m ⊕ s)
    - PSolve(pp, Z): Compute y ← rGC.Eval(C̃, C_T, x̃), unmask s = y·r ⊕ (r·m ⊕ s)

    Garbling modes:
      - "crgc": CRGC baseline (reusable XOR-flipped circuit; InputB plaintext).
      - "prgc": reusable section XOR-flipped once at setup; non-reusable
                section Yao-garbled FRESH per puzzle. The Yao section is
                sealed under an unlock key derived from the sequential
                chain's output, so the solver must perform the T sequential
                evaluations before it can touch any gate that reveals m.
    """

    def __init__(self, lam: int = 256, message_size: int = 256, T: int = 4,
                 use_sha256: bool = True, garbling_mode: str = "crgc"):
        """
        Args:
            lam: Security parameter (bits)
            message_size: Size of messages in bits
            T: Number of sequential iterations
            use_sha256: If True, use SHA-256 circuit (proper cryptographic security);
                       if False, use XOR mixing (lightweight, for testing)
            garbling_mode: "crgc" or "prgc" (see class docstring).
        """
        if garbling_mode not in ("crgc", "prgc"):
            raise ValueError(
                f"garbling_mode must be 'crgc' or 'prgc', got {garbling_mode!r}"
            )
        self.lam = lam
        self.message_size = message_size
        self.T = T
        self.use_sha256 = use_sha256
        self.garbling_mode = garbling_mode

        self.seq_func = SequentialFunction()

        seq_mode = 'sha256' if use_sha256 else 'xor_mixing'
        self.circuit = create_tlp_unrolled_circuit(
            T=T,
            message_bits=message_size,
            sequential_func=create_sequential_function_for_circuit(seq_mode)
        )

        # Public parameters (set by PSetup)
        self.pp = None  # Will be (C_tilde, pk) after setup

    def _bytes_to_bits(self, data: bytes) -> List[bool]:
        """Convert bytes to bits (LSB first)"""
        bits = []
        for byte in data:
            for i in range(8):
                bits.append(bool((byte >> i) & 1))
        return bits

    def _bits_to_bytes(self, bits: List[bool]) -> bytes:
        """Convert bits to bytes (LSB first)"""
        byte_list = []
        for i in range(0, len(bits), 8):
            byte_bits = bits[i:i+8]
            byte_val = 0
            for j, bit in enumerate(byte_bits):
                if bit:
                    byte_val |= (1 << j)
            byte_list.append(byte_val)
        return bytes(byte_list)

    def _prepare_inputs(self, b: int, x: bytes, m: bytes, z: bytes, i: int):
        """
        Prepare circuit inputs

        Circuit expects:
        - InputA: [b (1 bit), x (message_bits), i (i_bits)]
        - InputB: [m (message_bits), z (message_bits)]
        """
        x_bits = self._bytes_to_bits(x)
        m_bits = self._bytes_to_bits(m)
        z_bits = self._bytes_to_bits(z)
        b_bit = [bool(b)]

        i_bit_count = max(1, math.ceil(math.log2(self.T + 2)))
        i_bits = []
        for bit_idx in range(i_bit_count):
            i_bits.append(bool((i >> bit_idx) & 1))

        # Build inputs in order that circuit expects
        # InputA: b, x, i (to match circuit builder)
        inputA = b_bit + x_bits + i_bits
        # InputB: m, z (to match circuit builder)
        inputB = m_bits + z_bits

        return inputA, inputB

    def _eval_plain_full(self, inputA: List[bool], inputB: List[bool]) -> List[bool]:
        """Evaluate the original (un-garbled) circuit; return all wire values.

        Used by PGen to learn the logical values of boundary wires (outputs
        of reusable gates that feed non-reusable gates) so it can seal the
        matching Yao keys under K_unlock. Inputs/outputs reversed exactly
        like circuit_evaluator.
        """
        c = self.circuit
        evaluation = [False] * c.details.numWires
        for i in range(c.details.bitlengthInputA):
            evaluation[i] = inputA[c.details.bitlengthInputA - 1 - i]
        for i in range(c.details.bitlengthInputB):
            evaluation[i + c.details.bitlengthInputA] = \
                inputB[c.details.bitlengthInputB - 1 - i]
        for gate in c.gates:
            evaluation[gate.outputID] = gate.truthTable[
                int(evaluation[gate.leftParentID])
            ][int(evaluation[gate.rightParentID])]
        return evaluation

    def PSetup_Garble(self) -> Tuple:
        """
        PSetup(1^λ, T) - Setup algorithm from paper

        Returns:
            pp = (C̃, pk).

        CRGC mode: C̃ is the fully XOR-flipped circuit; pk = base_flipped.

        PRGC mode: only the REUSABLE gates are XOR-flipped (one-time cost);
        the non-reusable gates keep their original logical truth tables and
        are Yao-encrypted fresh per puzzle in PGen. pk holds the generator's
        secrets: the wire_flip pattern and the partition. The solver never
        receives pk.
        """
        num_wires = self.circuit.details.numWires
        inputa_len = self.circuit.details.bitlengthInputA
        inputb_len = self.circuit.details.bitlengthInputB
        num_outputs = self.circuit.details.numOutputs
        bitlength_outputs = self.circuit.details.bitlengthOutputs
        output_start = num_wires - num_outputs * bitlength_outputs

        C_tilde = copy.deepcopy(self.circuit)

        if self.garbling_mode == "crgc":
            # Initialize flip pattern matching C++ implementation:
            # - InputA wires: random flips
            # - InputB wires: never flipped (always False)
            # - Internal wires: random initial values (modified by get_flipped_circuit)
            # - Output wires: never flipped (enforced by get_flipped_circuit)
            num_random_bits = inputa_len + max(0, output_start - inputa_len - inputb_len)
            if num_random_bits > 0:
                random_bits_int = secrets.randbits(num_random_bits)
                random_bits = [(random_bits_int >> i) & 1 for i in range(num_random_bits)]
            else:
                random_bits = []

            random_idx = 0
            base_flipped = []
            for i in range(num_wires):
                if i < inputa_len:
                    base_flipped.append(bool(random_bits[random_idx]))
                    random_idx += 1
                elif i < inputa_len + inputb_len:
                    base_flipped.append(False)
                elif i >= output_start:
                    base_flipped.append(False)
                else:
                    base_flipped.append(bool(random_bits[random_idx]))
                    random_idx += 1

            get_flipped_circuit(C_tilde, base_flipped)
            pk = {'base_flipped': base_flipped, 'mode': 'crgc'}
            self.pp = (C_tilde, pk)
            return self.pp

        # ------------------------------------------------------------------
        # PRGC mode
        # ------------------------------------------------------------------

        # Step 1: partition. Non-reusable = gates downstream of InputB wires
        # and of leaked InputA wires (CRGC §2.5 rule), plus the final output
        # gates (their plaintext outputs would otherwise need a key→bit
        # conversion the solver cannot do). Structural analysis must run on
        # the UN-flipped circuit copy (truth tables determine gate types).
        non_reusable_gates: Set[int] = find_non_reusable_gates(C_tilde)
        non_reusable_gates |= {
            gi for gi, g in enumerate(C_tilde.gates)
            if g.outputID >= output_start
        }

        # Step 2: XOR-flip the REUSABLE gates only, recording every output
        # flip in wire_flip (mirroring get_flipped_circuit). Non-reusable
        # gates keep their ORIGINAL truth tables; PGen encrypts them per
        # puzzle.
        wire_flip: List[bool] = [False] * num_wires
        random_bits_int = secrets.randbits(max(1, inputa_len))
        for i in range(inputa_len):
            wire_flip[i] = bool((random_bits_int >> i) & 1)
        # InputB wires and output wires: never flipped (False already).

        reusable_indices = [
            gi for gi in range(len(C_tilde.gates)) if gi not in non_reusable_gates
        ]
        if reusable_indices:
            flip_rand = secrets.randbits(len(reusable_indices))
        else:
            flip_rand = 0
        for pos, gi in enumerate(reusable_indices):
            gate = C_tilde.gates[gi]
            # Parents of a reusable gate are input wires or outputs of other
            # reusable gates (a parent from the non-reusable section would
            # make this gate reachable from a secret wire, hence non-
            # reusable), so wire_flip[parent] is final at this point.
            if wire_flip[gate.leftParentID]:
                swap_left_parent(gate.truthTable)
            if wire_flip[gate.rightParentID]:
                swap_right_parent(gate.truthTable)
            decision = bool((flip_rand >> pos) & 1)
            if decision:
                flip_table(gate.truthTable)
            wire_flip[gate.outputID] = decision

        # Step 3: wires that carry Yao keys = parents and outputs of
        # non-reusable gates, plus every InputB wire (m/z must be hidden).
        wires_needing_keys: Set[int] = set()
        for gi in non_reusable_gates:
            gate = C_tilde.gates[gi]
            wires_needing_keys.add(gate.leftParentID)
            wires_needing_keys.add(gate.rightParentID)
            wires_needing_keys.add(gate.outputID)
        for w in range(inputa_len, inputa_len + inputb_len):
            wires_needing_keys.add(w)

        # Boundary wires: outputs of reusable gates consumed by non-reusable
        # gates. Their Yao keys are delivered per puzzle, SEALED under
        # K_unlock (see module docstring): the solver only learns the
        # wire-level values of these wires. (In particular the sequential
        # chain's output by evaluating the whole reusable section.)
        reusable_outputs: Set[int] = set()
        for gi in reusable_indices:
            reusable_outputs.add(C_tilde.gates[gi].outputID)
        boundary_wires: Set[int] = set()
        for gi in non_reusable_gates:
            gate = C_tilde.gates[gi]
            for parent in (gate.leftParentID, gate.rightParentID):
                if parent in reusable_outputs:
                    boundary_wires.add(parent)

        pk = {
            'mode': 'prgc',
            'wire_flip': wire_flip,
            'non_reusable_gates': non_reusable_gates,
            'wires_needing_keys': wires_needing_keys,
            'boundary_wires': boundary_wires,
        }
        self.pp = (C_tilde, pk)
        return self.pp

    def PGen(self, s: int, pp: Tuple = None) -> Tuple:
        """
        PGen(pp, s) - Puzzle generation algorithm from paper

        Given s ∈ {0,1}:
        - Sample random x ← {0,1}^λ, m ← {0,1}^λ, r ← {0,1}^λ
        - Compute x̃ ← rGC.Enc(pk, (0, x, m, 0^λ, 1))
        - Return Z = (x̃, r, r·m ⊕ s)

        PRGC mode garbles the non-reusable section FRESH for this puzzle
        (new key pairs, new encrypted tables) and seals the boundary keys
        under K_unlock = SHA256(packed boundary wire values). Keys, tables
        and the unlock seal are all shipped inside x̃.
        """
        if pp is None:
            if self.pp is None:
                raise ValueError("Must call PSetup_Garble() first or provide pp")
            pp = self.pp

        C_tilde, pk = pp

        # Sample random values using the circuit's message size so that the
        # encoded inputs match the circuit's bit widths.
        x = secrets.token_bytes(self.message_size // 8)
        m = secrets.token_bytes(self.message_size // 8)
        r = secrets.token_bytes(self.lam // 8)
        z_zero = bytes(self.message_size // 8)

        # Goldreich-Levin masking: r·m ⊕ s (over the common prefix if
        # lam != message_size)
        r_int = int.from_bytes(r, 'big')
        m_int = int.from_bytes(m, 'big')
        r_dot_m = bin(r_int & m_int).count('1') % 2
        r_dot_m_xor_s = r_dot_m ^ s

        # Prepare circuit inputs
        inputA, inputB = self._prepare_inputs(b=0, x=x, m=m, z=z_zero, i=1)

        inputa_len = self.circuit.details.bitlengthInputA

        if pk.get('mode') != 'prgc':
         
            base_flipped = pk['base_flipped']

            encoded_inputA = []
            for i in range(len(inputA)):
                wire_idx = len(inputA) - 1 - i  # Reverse indexing for C++ compatibility
                if base_flipped[wire_idx]:
                    encoded_inputA.append(not inputA[i])
                else:
                    encoded_inputA.append(inputA[i])

            # InputB is not encoded in CRGC  (it's sent in plaintext as per the CRGC paper)
            encoded_inputB = list(inputB)

            x_tilde = (encoded_inputA, encoded_inputB)
            Z = (x_tilde, r, r_dot_m_xor_s)
            return Z

        # ------------------------------------------------------------------
        # PRGC encoding: fresh keys + fresh tables, sealed boundary keys
        # ------------------------------------------------------------------
        wire_flip = pk['wire_flip']
        wires_needing_keys = pk['wires_needing_keys']
        non_reusable_gates = pk['non_reusable_gates']
        boundary_wires = pk['boundary_wires']

        details = C_tilde.details
        output_start = details.numWires - details.numOutputs * details.bitlengthOutputs

        # Fresh per-wire key pairs. Key index v is the WIRE-LEVEL bit
        # (logical ⊕ wire_flip[w]); key K_w[v] carries select bit v ⊕ π_w
        # with π_w a fresh random per-wire permutation bit (point-and-
        # permute: the solver picks rows by select bit and learns nothing).
        perm: Dict[int, int] = {}
        yao_keys: Dict[int, Tuple[bytes, bytes]] = {}
        for w in wires_needing_keys:
            p = secrets.randbits(1)
            perm[w] = p
            yao_keys[w] = (
                gen_key_with_select_bit(p),
                gen_key_with_select_bit(1 - p),
            )

        # Seal the boundary keys under K_unlock. The preimage is the packed
        # wire-level values of ALL boundary wires (sorted by wire id); it
        # includes the sequential chain's output wires, so the solver must
        # finish the reusable section before it can open the seal.
        boundary: Dict[int, bytes] = {}
        if boundary_wires:
            plain = self._eval_plain_full(inputA, inputB)
            sorted_bw = sorted(boundary_wires)
            pre_bits = [
                int(bool(plain[w])) ^ int(wire_flip[w]) for w in sorted_bw
            ]
            k_unlock = unlock_key(pack_bits(pre_bits))
            for w, v in zip(sorted_bw, pre_bits):
                boundary[w] = xor_bytes(
                    yao_keys[w][v], boundary_mask(k_unlock, w)
                )

        # Fresh encrypted truth tables for the non-reusable gates.
        # Row (a, b) is indexed by the SELECT BITS of the two parent keys.
        tables: Dict[int, List[List[bytes]]] = {}
        for gi in non_reusable_gates:
            gate = C_tilde.gates[gi]
            l, rr, o = gate.leftParentID, gate.rightParentID, gate.outputID
            K_l, K_r, K_o = yao_keys[l], yao_keys[rr], yao_keys[o]
            p_l, p_r = perm[l], perm[rr]
            f_l, f_r, f_o = wire_flip[l], wire_flip[rr], wire_flip[o]
            table = gate.truthTable  # ORIGINAL logical table (never flipped)
            rows = [[None, None], [None, None]]
            for a in (0, 1):
                for b in (0, 1):
                    k_l = K_l[a ^ p_l]
                    k_r = K_r[b ^ p_r]
                    logical_l = (a ^ p_l) ^ int(f_l)
                    logical_r = (b ^ p_r) ^ int(f_r)
                    logical_out = int(bool(table[logical_l][logical_r]))
                    v_out = logical_out ^ int(f_o)
                    rows[a][b] = xor_bytes(K_o[v_out], pad(k_l, k_r, gi))
            tables[gi] = rows

        # Encode inputs (reverse indexing matches CRGC's wire layout).
        # - InputB wires always carry keys only (m/z never appear in
        #   plaintext and never feed reusable gates, since any consumer of
        #   InputB is non-reusable by construction).
        # - InputA wires that feed only the reusable section carry the
        #   CRGC XOR-masked bit; InputA wires that also parent non-reusable
        #   gates carry (masked bit, key) so each consumer gets the right
        #   token.
        encoded_inputA = []
        for i in range(len(inputA)):
            wire_idx = len(inputA) - 1 - i
            masked = bool(int(inputA[i]) ^ int(wire_flip[wire_idx]))
            if wire_idx in yao_keys:
                key = yao_keys[wire_idx][int(inputA[i]) ^ int(wire_flip[wire_idx])]
                encoded_inputA.append((masked, key))
            else:
                encoded_inputA.append(masked)

        encoded_inputB = []
        for i in range(len(inputB)):
            wire_idx = inputa_len + len(inputB) - 1 - i
            key = yao_keys[wire_idx][int(inputB[i])]  # wire_flip = 0 on InputB
            encoded_inputB.append(key)

        # Output decoding: for each output wire, reveal the select bit of
        # K^0 (standard Yao output decoding table).
        out_perm = {w: perm[w] for w in range(output_start, details.numWires)}

        yao_material = {
            'tables': tables,
            'boundary': boundary,        # SEALED under K_unlock
            'out_perm': out_perm,
            'non_reusable': sorted(non_reusable_gates),
        }

        x_tilde = (encoded_inputA, encoded_inputB, yao_material)
        Z = (x_tilde, r, r_dot_m_xor_s)
        return Z

    def PSolve(self, Z: Tuple, pp: Tuple = None) -> Tuple[int, bytes]:
        """
        PSolve(Z, pp) - Puzzle solving algorithm from paper.

        Compute:
        - y ← rGC.Eval(C̃, C_T, x̃)
        - s = y·r ⊕ (r·m ⊕ s)  [unmask]

        PRGC mode: the solver evaluates using ONLY the public circuit C̃
        and the puzzle Z. It must evaluate the entire reusable
        (sequential) section first: the Yao section's boundary keys are
        sealed under K_unlock, which is derived from the chain's output
        wire values.

        Returns:
            (s, y): the recovered secret bit and the circuit-output
                    witness needed by PVerify.
        """
        if pp is None:
            if self.pp is None:
                raise ValueError("Must call PSetup_Garble() first or provide pp")
            pp = self.pp

        x_tilde, r, r_dot_m_xor_s = Z
        C_tilde, pk = pp

        mode = pk.get('mode', 'crgc')
        if mode == 'crgc':
            encoded_inputA, encoded_inputB = x_tilde
            y_bits = evaluate_transformed_circuit(
                C_tilde, encoded_inputA, encoded_inputB
            )
        else:
            encoded_inputA, encoded_inputB, yao_material = x_tilde
            y_bits = self._evaluate_prgc(
                C_tilde, encoded_inputA, encoded_inputB, yao_material
            )

        # Output bits are plaintext logical bits in both modes.
        y = self._bits_to_bytes(y_bits)

        # Unmask secret: s = (r·m ⊕ s) ⊕ (y·r)
        r_int = int.from_bytes(r, 'big')
        y_int = int.from_bytes(y, 'big')
        y_dot_r = bin(y_int & r_int).count('1') % 2
        s = r_dot_m_xor_s ^ y_dot_r

        return s, y

    def PVerify(self, s_candidate: int, y: bytes, Z: Tuple) -> bool:
        """
        PVerify(s', y, Z) - Verification algorithm from paper.

        Constant-time integrity check on the solver's claimed (s', y) pair
        against the puzzle's commitment r·m ⊕ s. The verifier computes the Goldreich-Levin inner product
        and compare. 
        Args:
            s_candidate: bit the solver claims is the secret (s' ∈ {0,1}).
            y:          circuit output the solver claims equals m.
            Z:          puzzle (x̃, r, r·m ⊕ s).

        Returns:
            bool: True iff s_candidate is consistent, i.e. r·y ⊕ s_candidate
                  equals r·m ⊕ s.

        Cost: O(λ) — one XOR-folded inner product. Independent of T.
        """
        if s_candidate not in (0, 1):
            raise ValueError(f"s_candidate must be 0 or 1, got {s_candidate!r}")

        _x_tilde, r, r_dot_m_xor_s = Z

        r_int = int.from_bytes(r, 'big')
        y_int = int.from_bytes(y, 'big')
        y_dot_r = bin(y_int & r_int).count('1') % 2
        reconstructed = y_dot_r ^ s_candidate
        return reconstructed == r_dot_m_xor_s


    def _evaluate_prgc(self, C_tilde, encoded_inputA, encoded_inputB,
                       yao_material) -> List[bool]:
        """
        Solver-side PRGC evaluation, two passes:

        Pass 1 (sequential work): evaluate every reusable gate on wire-level
        bits. This computes the boundary wire values — including the chain
        output f^T(x) — which the solver packs and hashes to derive
        K_unlock and open the sealed boundary keys.

        Pass 2 (Yao section): decrypt the fresh per-puzzle tables with the
        delivered input keys, the unsealed boundary keys, and the keys
        recovered from earlier non-reusable gates (row chosen by the
        point-and-permute select bits). Decode outputs via out_perm.
        """
        details = C_tilde.details
        tables = yao_material['tables']
        boundary_sealed = yao_material['boundary']
        out_perm = yao_material['out_perm']
        non_reusable_gates = set(yao_material['non_reusable'])

        # evaluation[w] is one of:
        #   bool              — wire-level bit (reusable section)
        #   (bool, bytes)     — InputA wire feeding both sections
        #   bytes             — Yao key (non-reusable section)
        evaluation: List[Union[bool, bytes, tuple]] = [False] * details.numWires

        # Load InputA (reversed for C++ compatibility)
        for i in range(details.bitlengthInputA):
            evaluation[i] = encoded_inputA[details.bitlengthInputA - 1 - i]

        # Load InputB (reversed)
        for j in range(details.bitlengthInputB):
            wire_id = details.bitlengthInputA + j
            evaluation[wire_id] = encoded_inputB[details.bitlengthInputB - 1 - j]

        def _as_bit(v, wire):
            """Wire-level bit for a reusable gate's parent."""
            if isinstance(v, bool):
                return int(v)
            if isinstance(v, tuple):
                return int(v[0])
            raise TypeError(
                f"Reusable gate received a Yao-key input on wire {wire}; "
                "the partition should prevent non-reusable outputs from "
                "feeding reusable gates."
            )

        # ---- Pass 1: reusable (sequential) section ----
        for gi, gate in enumerate(C_tilde.gates):
            if gi in non_reusable_gates:
                continue
            li = _as_bit(evaluation[gate.leftParentID], gate.leftParentID)
            ri = _as_bit(evaluation[gate.rightParentID], gate.rightParentID)
            evaluation[gate.outputID] = bool(gate.truthTable[li][ri])

        # ---- Unseal the boundary keys ----
        boundary: Dict[int, bytes] = {}
        if boundary_sealed:
            sorted_bw = sorted(boundary_sealed)
            pre_bits = [int(evaluation[w]) for w in sorted_bw]
            k_unlock = unlock_key(pack_bits(pre_bits))
            for w in sorted_bw:
                boundary[w] = xor_bytes(
                    boundary_sealed[w], boundary_mask(k_unlock, w)
                )

        def _as_key(v, wire):
            """Yao key for a non-reusable gate's parent."""
            if isinstance(v, bytes):
                return v
            if isinstance(v, tuple):
                return v[1]
            # bool: boundary crossing — use the unsealed key
            return boundary[wire]

        # ---- Pass 2: non-reusable (Yao) section ----
        for gi, gate in enumerate(C_tilde.gates):
            if gi not in non_reusable_gates:
                continue
            k_l = _as_key(evaluation[gate.leftParentID], gate.leftParentID)
            k_r = _as_key(evaluation[gate.rightParentID], gate.rightParentID)
            a = select_bit(k_l)
            b = select_bit(k_r)
            ct = tables[gi][a][b]
            evaluation[gate.outputID] = xor_bytes(ct, pad(k_l, k_r, gi))

        # Extract outputs (reversed, like the C++ evaluator) and decode.
        output = []
        for i in range(details.numOutputs):
            for j in range(details.bitlengthOutputs):
                wire_idx = details.numWires - 1 - j - details.bitlengthOutputs * i
                key = evaluation[wire_idx]
                output.append(bool(select_bit(key) ^ out_perm[wire_idx]))
        return output

    def run_protocol(self, s: int):
        """
        Run complete protocol: PSetup -> PGen -> PSolve -> PVerify.

        Args:
            s: Secret bit (s ∈ {0,1})

        Returns:
            bool: True iff PVerify accepts the solver's recovered secret.
        """
        pp = self.PSetup_Garble()
        Z = self.PGen(s, pp)
        s_recovered, y = self.PSolve(Z, pp)
        return self.PVerify(s_recovered, y, Z)


if __name__ == "__main__":
    print("TLP Python Garbling Library v4")
    print("Use: from tlp_garbling4 import PythonGarbledTLP4")
