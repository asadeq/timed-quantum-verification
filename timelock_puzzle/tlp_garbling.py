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
from typing import Tuple, List, Union

from .tlp_circuit_builder import create_tlp_unrolled_circuit
from .sequential_functions import SequentialFunction, create_sequential_function_for_circuit
from crgc_garbled_circuits import *
from crgc_garbled_circuits.circuit_flipper import get_flipped_circuit
from crgc_garbled_circuits.circuit_evaluator import evaluate_transformed_circuit


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
    
    Performance: Garbling is one-time, amortized over many puzzle generations.
    """

    def __init__(self, lam: int = 256, message_size: int = 256, T: int = 4, use_sha256: bool = True):
        """
        Args:
            lam: Security parameter (bits)
            message_size: Size of messages in bits
            T: Number of sequential iterations
            use_sha256: If True, use SHA-256 circuit (proper cryptographic security);
                       if False, use XOR mixing (lightweight, for testing)
                       
        """
        self.lam = lam
        self.T = T
        self.use_sha256 = use_sha256
        
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
        
        base_flipped = []
        for i in range(num_wires):
            if i < inputa_len:
                # InputA wire: random flip
                base_flipped.append(secrets.choice([True, False]))
            elif i < inputa_len + inputb_len:
                # InputB wire: never flipped (matches C++ implementation)
                base_flipped.append(False)
            elif i >= output_start:
                # Output wire: never flipped (matches C++ implementation)
                base_flipped.append(False)
            else:
                # Internal wire: random initial value (will be modified by get_flipped_circuit)
                base_flipped.append(secrets.choice([True, False]))
        
        C_tilde = copy.deepcopy(self.circuit)
        get_flipped_circuit(C_tilde, base_flipped)
        
        pk = {'base_flipped': base_flipped}
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
        
        # Sample random values (using self.lam bytes, not hardcoded 32)
        x = secrets.token_bytes(self.lam // 8)
        m = secrets.token_bytes(self.lam // 8)
        r = secrets.token_bytes(self.lam // 8)
        z_zero = bytes(self.lam // 8)
        
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
        
        # Encode inputA according to base garbling: if wire is flipped, send NOT(input)
        encoded_inputA = []
        for i in range(len(inputA)):
            wire_idx = len(inputA) - 1 - i  # Reverse indexing for C++ compatibility
            if base_flipped[wire_idx]:
                encoded_inputA.append(not inputA[i])
            else:
                encoded_inputA.append(inputA[i])
        
        # InputB is NOT encoded in CRGC - it's sent in plaintext
        # This matches the C++ implementation which sets flipped[inputB_wires] = 0
        encoded_inputB = inputB
        
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
        y_bits = evaluate_transformed_circuit(C_tilde, encoded_inputA, encoded_inputB)
        
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
