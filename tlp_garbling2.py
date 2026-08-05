"""
Complete Python-based TLP with Circuit Garbling

This demonstrates the full TLP protocol using CRGC garbling:
1. PSetup: Garble circuit ONCE using get_flipped_circuit (transforms truth tables)
2. PGen: Generate puzzle with fresh input encoding (reuses garbled circuit)
3. PSolve: Evaluate pre-garbled circuit with puzzle-specific inputs to recover secret

note: Circuit is garbled once in PSetup, then reused with different input
encodings per puzzle. This amortizes the garbling cost across multiple puzzles.
"""

import secrets
import copy
import math
from collections import deque
from typing import Tuple, List, Union, Set

from .Quantum_vertification_artifact.timelock_puzzle.tlp_circuit_builder import create_tlp_unrolled_circuit
from .Quantum_vertification_artifact.timelock_puzzle.sequential_functions import SequentialFunction, create_sequential_function_for_circuit
from .Quantum_vertification_artifact.timelock_puzzle.yao_helpers import gen_key, garble_bit, ungarble_bit
from .Quantum_vertification_artifact.timelock_puzzle.prgc_partition import find_non_reusable_gates
from crgc_garbled_circuits import *
from crgc_garbled_circuits.circuit_flipper import get_flipped_circuit
from crgc_garbled_circuits.circuit_evaluator import evaluate_transformed_circuit


class PythonGarbledTLP2:
    """
    Time-Lock Puzzle from Lattices (Agrawal et al. 2024) - Construction 4.1
    
    Circuit C(b, x, m, z, i):
      - If i = T+1: return m if b=0, else x⊕z
      - Otherwise: return (b, f(x), m, z, i+1)
    
    - PSetup(1^λ, T): Returns pp = (C̃, pk) where C̃ ← rGC.Garble(1^λ, C_T)
    - PGen(pp, s): Sample x,m,r ← {0,1}^λ, encode x̃ ← rGC.Enc(pk, (0,x,m,0^λ,1)),
                   return Z = (x̃, r, r·m ⊕ s)
    - PSolve(pp, Z): Compute y ← rGC.Eval(C̃, C_T, x̃), unmask s = y·r ⊕ (r·m ⊕ s)
    
    Performance: Garbling is one-time, amortized over many puzzle generations.
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
            garbling_mode: "crgc" (default) uses Completely Reusable Garbled
                           Circuits as in [48]; reusable across puzzles but
                           leaks generator inputs under single-player
                           adversary (see CRGC §2.2). In this mode InputB is
                           the evaluator's plaintext input, so secrets such as
                           m must not be placed there. "prgc" uses the
                           Partially Reusable variant from CRGC §2.5: leaking
                           gates are Yao-garbled with per-wire SHA-256-derived
                           keys delivered per-puzzle, satisfying the IND-CPA
                           security of Definition 3.2 in the classical setting.
                           In PRGC mode all InputB wires are given Yao keys so
                           the solver cannot read m/z without evaluating the circuit.
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
    
    def PSetup_Garble(self) -> Tuple:
        """
        PSetup(1^λ, T) - Setup algorithm from paper
        
        Computes (C̃, pk) ← rGC.Garble(1^λ, C_T) where C_T is the T-fold repetition
        of circuit C(b, x, m, z, i). Garbles circuit ONCE during setup.
        
        Returns:
            pp = (C̃, pk) where:
            - C̃: Garbled circuit (truth tables transformed, reusable)
            - pk: Encoding key (contains base_flipped pattern for rGC.Enc)
        """
        # Initialize flip pattern matching C++ implementation:
        # - InputA wires: random flips
        # - InputB wires: never flipped (always False)
        # - Internal wires: random initial values (will be modified by get_flipped_circuit)
        # - Output wires: never flipped (always False) - enforced by get_flipped_circuit
        num_wires = self.circuit.details.numWires
        inputa_len = self.circuit.details.bitlengthInputA
        inputb_len = self.circuit.details.bitlengthInputB
        num_outputs = self.circuit.details.numOutputs
        bitlength_outputs = self.circuit.details.bitlengthOutputs
        output_start = num_wires - num_outputs * bitlength_outputs
        
     
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
                # InputA wire: random flip
                base_flipped.append(bool(random_bits[random_idx]))
                random_idx += 1
            elif i < inputa_len + inputb_len:
                # InputB wire: never flipped (matches C++ implementation)
                base_flipped.append(False)
            elif i >= output_start:
                # Output wire: never flipped (matches C++ implementation)
                base_flipped.append(False)
            else:
                # Internal wire: random initial value (will be modified by get_flipped_circuit)
                base_flipped.append(bool(random_bits[random_idx]))
                random_idx += 1
        

        C_tilde = copy.deepcopy(self.circuit)

        if self.garbling_mode == "crgc":
            # CRGC: standard XOR-flip all gates. Output gates cannot be
            # flipped, so the output wires carry the actual logical bits.
            get_flipped_circuit(C_tilde, base_flipped)
            pk = {'base_flipped': base_flipped, 'mode': 'crgc'}
            self.pp = (C_tilde, pk)
            return self.pp

        # PRGC mode: reusable gates get XOR-flipped truth tables (as in CRGC);
        # non-reusable gates keep their original tables and get Yao-encrypted.
        # See README §"Garbling modes" for the high-level distinction.

        # Step 1: identify non-reusable gates. Structural analysis is
        # insensitive to the XOR-flip state, so run it on the un-flipped
        # circuit copy.
        non_reusable_gates: Set[int] = find_non_reusable_gates(C_tilde)

        # Step 1b: closure extension — any gate feeding a non-reusable
        # parent must itself be non-reusable so the chain carries Yao keys.
        changed = True
        while changed:
            changed = False
            parent_wires = set()
            for gi in non_reusable_gates:
                gate = C_tilde.gates[gi]
                parent_wires.add(gate.leftParentID)
                parent_wires.add(gate.rightParentID)
            for gi, gate in enumerate(C_tilde.gates):
                if gi in non_reusable_gates:
                    continue
                if gate.outputID in parent_wires:
                    non_reusable_gates.add(gi)
                    changed = True

        # Step 2: XOR-flip the REUSABLE gates only. Non-reusable gates
        # must keep their original (logical) truth tables so that after
        # Yao encryption, decryption recovers the logical output bit
        # directly (without an additional XOR-flip in the walker).
        from crgc_garbled_circuits.helper_functions import (
            swap_left_parent,
            swap_right_parent,
            flip_table,
        )

        # Only REUSABLE gates get the random output XOR-flip. Track which
        # gate index (within the full C_tilde.gates list) each flippable
        # reusable gate corresponds to, so we can address flip_decisions
        # by position among reusable flippable gates.
        gate_index_in_circuit = {id(g): i for i, g in enumerate(C_tilde.gates)}
        reusable_flippable_indices = [
            gate_index_in_circuit[id(g)]
            for g in C_tilde.gates
            if g.outputID < output_start
            and gate_index_in_circuit[id(g)] not in non_reusable_gates
        ]
        num_reusable_flippable = len(reusable_flippable_indices)
        if num_reusable_flippable > 0:
            random_int = secrets.randbits(num_reusable_flippable)
            flip_decisions = [
                bool((random_int >> i) & 1) for i in range(num_reusable_flippable)
            ]
        else:
            flip_decisions = []

        # Build a gate_index -> flip_decision_index map.
        gate_to_flip_decision = {}
        for flip_pos, gi in enumerate(reusable_flippable_indices):
            gate_to_flip_decision[gi] = flip_decisions[flip_pos]

        for gi, gate in enumerate(C_tilde.gates):
            if gi in non_reusable_gates:
                # Non-reusable gates keep their ORIGINAL truth tables
                # (un-flipped) so that after Yao encryption, decryption
                # recovers the logical output bit directly.
                continue
            # XOR-flip absorption for parent wires — REUSABLE gates only.
            if base_flipped[gate.leftParentID]:
                swap_left_parent(gate.truthTable)
            if base_flipped[gate.rightParentID]:
                swap_right_parent(gate.truthTable)
            if gate.outputID < output_start and gi in gate_to_flip_decision:
                if gate_to_flip_decision[gi]:
                    flip_table(gate.truthTable)
        yao_keys: dict = {}  # wire_id -> (K_w^0, K_w^1)

        # A wire needs a per-bit Yao key if it is either (a) a parent of a
        # non-reusable gate (PGen delivers the matching key per-puzzle), or
        # (b) the output of a non-reusable gate (used to chain downstream
        # non-reusable gates through their parent slots).
        wires_needing_keys: Set[int] = set()
        for gi in non_reusable_gates:
            gate = C_tilde.gates[gi]
            wires_needing_keys.add(gate.leftParentID)
            wires_needing_keys.add(gate.rightParentID)
            wires_needing_keys.add(gate.outputID)

        # In PRGC mode we want the solver to learn nothing about the
        # generator's input (including InputB, which carries the secret m/z).
        # Ensure every InputB wire receives a Yao key so that the puzzle
        # encoding hides those bits.
        for w in range(inputa_len, inputa_len + inputb_len):
            wires_needing_keys.add(w)

        # Output wires never get Yao keys (they are plaintext in CRGC).
        for w in list(wires_needing_keys):
            if w >= output_start:
                wires_needing_keys.discard(w)

        for w in wires_needing_keys:
            yao_keys[w] = (gen_key(), gen_key())

        # Double-key encrypt the truth table of every non-reusable gate.
        for gi in non_reusable_gates:
            gate = C_tilde.gates[gi]
            K_l = yao_keys[gate.leftParentID]
            K_r = yao_keys[gate.rightParentID]
            for li in (0, 1):
                for ri in (0, 1):
                    gate.truthTable[li][ri] = garble_bit(
                        gate.truthTable[li][ri], K_l[li], K_r[ri]
                    )

        pk = {
            'base_flipped': base_flipped,
            'mode': 'prgc',
            'yao_keys': yao_keys,
            'non_reusable_gates': non_reusable_gates,
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
        
        Args:
            s: Secret bit to encrypt (s ∈ {0,1})
            pp: Public parameters (C̃, pk). If None, uses self.pp
            
        Returns:
            Z = (x̃, r, r·m ⊕ s) where r·m is Goldreich-Levin inner product
        """
        # Use provided pp or default to self.pp
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
        
        # Goldreich-Levin masking: r·m ⊕ s
        r_int = int.from_bytes(r, 'big')
        m_int = int.from_bytes(m, 'big')
        r_dot_m = bin(r_int & m_int).count('1') % 2
        r_dot_m_xor_s = r_dot_m ^ s
        
        # Prepare circuit inputs
        inputA, inputB = self._prepare_inputs(b=0, x=x, m=m, z=z_zero, i=1)

        # For garbled circuits: encode inputs according to the base garbling pattern
        # The circuit was already garbled in PSetup with base_flipped pattern
        # We need to encode our actual inputs to match that garbling
        base_flipped = pk['base_flipped']
        yao_keys = pk.get('yao_keys', {}) if pk.get('mode') == 'prgc' else {}

        # Helper: decide encoding for one wire based on whether the wire
        def encode_wire(wire_idx: int, bit: bool):
            # Yao section: send the appropriate per-wire key.
            if wire_idx in yao_keys:
                k0, k1 = yao_keys[wire_idx]
                return k1 if bit else k0
            # CRGC section: XOR with public mask for InputA, plaintext for InputB.
            if wire_idx < self.circuit.details.bitlengthInputA and base_flipped[wire_idx]:
                return not bit
            return bit

        # Encode inputA — reverse indexing matches CRGC's wire layout
        # (the C++ evaluator reverses the bits so wire 0 is the MSB).
        encoded_inputA = []
        for i in range(len(inputA)):
            wire_idx = len(inputA) - 1 - i
            encoded_inputA.append(encode_wire(wire_idx, inputA[i]))

        # Encode inputB — same convention; in PRGC mode the wire may carry
        # a Yao key if it feeds a non-reusable gate.
        # For InputB the wire id in the full wire space is
        # bitlengthInputA + (bitlengthInputB - 1 - i).
        encoded_inputB = []
        inputa_len = self.circuit.details.bitlengthInputA
        for i in range(len(inputB)):
            wire_idx = inputa_len + len(inputB) - 1 - i
            encoded_inputB.append(encode_wire(wire_idx, inputB[i]))
        
        # x̃ = rGC.Enc(pk, (0, x, m, 0^λ, 1))
        # Contains encoded inputs for the garbled circuit C̃ from PSetup
        x_tilde = (encoded_inputA, encoded_inputB)
        
        # Return Z = (x̃, r, r·m ⊕ s) as per paper
        Z = (x_tilde, r, r_dot_m_xor_s)
        return Z
    
    def PSolve(self, Z: Tuple, pp: Tuple = None) -> int:
        """
        PSolve(pp, Z) - Puzzle solving algorithm from paper
        
        Compute:
        - y ← rGC.Eval(C̃, C_T, x̃)
        - s = y·r ⊕ (r·m ⊕ s)  [unmask]
        
        Args:
            Z: Puzzle (x̃, r, r·m ⊕ s)
            pp: Public parameters (C̃, pk). If None, uses self.pp
            
        Returns:
            s: Recovered secret bit
        """
        
        # Use provided pp or default to self.pp
        if pp is None:
            if self.pp is None:
                raise ValueError("Must call PSetup_Garble() first or provide pp")
            pp = self.pp
        
        # Unpack Z = (x̃, r, r·m ⊕ s)
        x_tilde, r, r_dot_m_xor_s = Z
        C_tilde, pk = pp
        encoded_inputA, encoded_inputB = x_tilde

        # Evaluate garbled circuit: y ← rGC.Eval(C̃, C_T, x̃)
        # With b=0 input, circuit returns m after T iterations
        # C̃ was garbled once in PSetup, x̃ is encoded to match that garbling
        #
        # In CRGC mode this is a single library call. In PRGC mode we walk
        # the gates manually so we can Yao-decrypt the non-reusable gates.
        mode = pk.get('mode', 'crgc')
        if mode == 'crgc':
            y_bits = evaluate_transformed_circuit(
                C_tilde, encoded_inputA, encoded_inputB
            )
        else:
            y_bits = self._evaluate_prgc(
                C_tilde, pk, encoded_inputA, encoded_inputB
            )
        
        # Output bits are NOT encoded in CRGC (output wires cannot be flipped)
        # So y_bits can be used directly
        y = self._bits_to_bytes(y_bits)
        
        # Unmask secret: s = (r·m ⊕ s) ⊕ (y·r)
        # Since y = m, this computes: s = (r·m ⊕ s) ⊕ r·m = s
        r_int = int.from_bytes(r, 'big')
        y_int = int.from_bytes(y, 'big')
        y_dot_r = bin(y_int & r_int).count('1') % 2
        s = r_dot_m_xor_s ^ y_dot_r
        
        return s
    
    def _evaluate_prgc(self, C_tilde, pk, encoded_inputA, encoded_inputB) -> List[bool]:
        """
        Evaluate the PRGC garbled circuit: truth-table walk for reusable
        gates, Yao-decrypt for non-reusable gates. See the paper's PRGC
        definition and the README §"Garbling modes" for the encoding
        convention (evaluation[w] is bool for reusable, bytes for non-
        reusable wires).
        """
        details = C_tilde.details
        yao_keys = pk.get('yao_keys', {})
        non_reusable_gates = pk.get('non_reusable_gates', set())
        base_flipped = pk.get('base_flipped', [False] * details.numWires)

        # evaluation[w] holds a bool (wire-level bit from CRGC section) or
        # bytes (per-bit Yao key from PRGC section). See README §"Garbling
        # modes" for the encoding invariant.
        evaluation: List[Union[bool, bytes, None]] = [False] * details.numWires

        # Load InputA (reversed for C++ compatibility)
        # Wire id i (0..bitlengthInputA-1) corresponds to encoded_inputA[bitlengthInputA-1-i].
        for i in range(details.bitlengthInputA):
            value = encoded_inputA[details.bitlengthInputA - 1 - i]
            if i in yao_keys:
                evaluation[i] = value  # bytes (Yao key)
            else:
                evaluation[i] = bool(value)  # wire-level encoded bit

        # Load InputB (reversed). Wire id (inputa_len + j) corresponds to
        # encoded_inputB[bitlengthInputB-1-j].
        for j in range(details.bitlengthInputB):
            wire_id = details.bitlengthInputA + j
            value = encoded_inputB[details.bitlengthInputB - 1 - j]
            if wire_id in yao_keys:
                evaluation[wire_id] = value
            else:
                evaluation[wire_id] = bool(value)

        # Walk gates in topological order
        for gi, gate in enumerate(C_tilde.gates):
            left_val = evaluation[gate.leftParentID]
            right_val = evaluation[gate.rightParentID]

            is_non_reusable = gi in non_reusable_gates

            def _to_logical_bit(v, w):
                """Logical (un-flipped) bit. Un-XOR base_flipped for bools."""
                if isinstance(v, bool):
                    return int(v ^ base_flipped[w])
                if isinstance(v, bytes):
                    return 1 if v == yao_keys[w][1] else 0
                raise TypeError(f"Unexpected evaluation cell: {type(v)}")

            def _to_wire_bit(v, w):
                """Wire-level (XOR-flipped) bit. For bytes inputs from the
                non-reusable section, apply base_flipped so the value
                matches a reusable gate's flipped truth table."""
                if isinstance(v, bool):
                    return int(v)
                if isinstance(v, bytes):
                    logical = 1 if v == yao_keys[w][1] else 0
                    return logical ^ base_flipped[w]
                raise TypeError(f"Unexpected evaluation cell: {type(v)}")

            if is_non_reusable:
                # Non-reusable gate: decrypt the stored ciphertext using the
                # delivered per-bit Yao keys. li/ri are inferred from which
                # key (K^0 or K^1) the PSolver was handed. All parents of a
                # non-reusable gate must be Yao keys so that the encrypted
                # truth table can be decrypted.
                if not isinstance(left_val, bytes) or not isinstance(right_val, bytes):
                    raise TypeError(
                        f"Non-reusable gate {gi} has a non-Yao input "
                        f"(left type={type(left_val)}, right type={type(right_val)}). "
                        "The PRGC partition should ensure every parent of a "
                        "non-reusable gate carries a Yao key."
                    )
                K_left_0, K_left_1 = yao_keys[gate.leftParentID]
                K_right_0, K_right_1 = yao_keys[gate.rightParentID]
                li = 1 if left_val == K_left_1 else 0
                ri = 1 if right_val == K_right_1 else 0
                ciphertext_bit = gate.truthTable[li][ri]
                out_bit = ungarble_bit(bool(ciphertext_bit), left_val, right_val)
                out_wire = gate.outputID
                if out_wire in yao_keys:
                    evaluation[out_wire] = yao_keys[out_wire][1 if out_bit else 0]
                else:
                    # Output feeds a reusable wire: store the wire-level bit
                    # (logical bit XOR the public base flip for that wire).
                    evaluation[out_wire] = bool(out_bit ^ base_flipped[out_wire])
            else:
                # Reusable gate: truth tables were XOR-flipped by
                # get_flipped_circuit, so feed them WIRE-LEVEL bits.
                li = _to_wire_bit(left_val, gate.leftParentID)
                ri = _to_wire_bit(right_val, gate.rightParentID)
                out_wire_level = bool(gate.truthTable[li][ri])
                out_wire = gate.outputID
                if out_wire in yao_keys:
                    # Output feeds a non-reusable parent: un-XOR to logical, map to Yao key.
                    logical_bit = out_wire_level ^ base_flipped[out_wire]
                    evaluation[out_wire] = yao_keys[out_wire][1 if logical_bit else 0]
                else:
                    evaluation[out_wire] = out_wire_level

        # Extract outputs (reversed, like the C++ evaluator)
        output = []
        for i in range(details.numOutputs):
            for j in range(details.bitlengthOutputs):
                wire_idx = details.numWires - 1 - j - details.bitlengthOutputs * i
                output.append(bool(evaluation[wire_idx]))
        return output

    def run_protocol(self, s: int):
        """
        Run complete protocol: PSetup -> PGen -> PSolve
        
        Args:
            s: Secret bit (s ∈ {0,1})
        
        Returns:
            bool: True if secret was recovered correctly
        """
        pp = self.PSetup_Garble()
        Z = self.PGen(s, pp)
        s_recovered = self.PSolve(Z, pp)
        
        return s_recovered == s


if __name__ == "__main__":
    print("TLP Python Garbling Library")
    print("Use: from tlp_python_garbling import PythonGarbledTLP")
