import numpy as np
import secrets
import math
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate
from qiskit.quantum_info import Statevector

# --- CONFIGURATION --
Q = 8  # Modulus (for security should be ~512)
N = 2   # Dimension of vectors (for security should be ~512)
BITS_PER_INT = int(math.log2(Q)) 

class LWE_KeyGen:
    @staticmethod
    def generate():
        # Generate keys in Z_Q
        s = np.random.randint(0, Q, size=N)
        A = np.random.randint(0, Q, size=(N, N))
        e = 0 # Small error vector; for simplicity, we set it to zero. In real LWE, this is small noise.
        u = np.dot(A, s) % Q + e
        return {'A': A, 'u': u}, {'s': s}

class QuantumAdder:
    """
    A generic arithmetic unit that works for any Modulo Q that is a power of 2.
    It builds the unitary matrix for 'x + C mod Q' and applies it.
    """
    @staticmethod
    def get_add_gate(const_val, num_qubits):
        """
        Creates a Quantum Gate that performs: |y> -> |(y + const_val) % Q>
        """
        dim = 2 ** num_qubits
        matrix = np.zeros((dim, dim))
        
        # Build the permutation matrix for addition mod 2^k
        for i in range(dim):
            target = (i + const_val) % dim
            matrix[target, i] = 1.0
            
        # Create a Qiskit Gate from this matrix
        gate = UnitaryGate(matrix, label=f"Add({const_val})")
        return gate

    @staticmethod
    def add_const_controlled(qc, ctrl_qubit, target_qubits, val):
        """
        Applies Controlled-Add(val).
        If ctrl_qubit is 1, add 'val' to target_qubits (modulo Q).
        """
        val = val % Q
        if val == 0: return

        # 1. Generate the adder gate for this specific constant
        add_gate = QuantumAdder.get_add_gate(val, len(target_qubits))
        
        # 2. Make it controlled (Standard C-U operation)
        c_add_gate = add_gate.control(1)
        
        # 3. Append to circuit
        # args: [control_bit] + [list of target bits]
        qc.append(c_add_gate, [ctrl_qubit] + target_qubits)

class Prover_Mahadev:
    def __init__(self):
        pass

    def build_oracle_mod_q(self, qc, pk, b_idx, x_indices, y_indices):
        A = pk['A']
        u = pk['u']
        
        # 1. Compute Ax (Mod Q)
        for j in range(N): # For each input integer x_j
            # x_j is composed of BITS_PER_INT qubits.
            # Each bit represents a value: 2^0, 2^1, 2^2...
            
            for bit_pos, ctrl_qubit in enumerate(x_indices[j]):
                # The value of this control bit is 2^bit_pos
                bit_value = 2 ** bit_pos
                
                # We need to add (A[i][j] * bit_value) to y_i
                for i in range(N):
                    scalar = (A[i][j] * bit_value)
                    QuantumAdder.add_const_controlled(qc, ctrl_qubit, y_indices[i], scalar)

        # 2. Add bu (Mod Q)
        for i in range(N):
            scalar = u[i]
            QuantumAdder.add_const_controlled(qc, b_idx, y_indices[i], scalar)

    def step2_commit(self, pk):
        print(f"[Prover] Initializing Quantum Memory for Q={Q}...")
        
        num_x_qubits = N * BITS_PER_INT
        num_y_qubits = N * BITS_PER_INT
        total_qubits = 1 + num_x_qubits + num_y_qubits
        
        qc = QuantumCircuit(total_qubits)
        
        # 1. Superposition
        qc.h(range(1 + num_x_qubits))
        
        # 2. Oracle
        b_idx = 0
        # Helper to slice qubit indices into chunks of size BITS_PER_INT
        x_indices = []
        for i in range(N):
            start = 1 + (i * BITS_PER_INT)
            x_indices.append(list(range(start, start + BITS_PER_INT)))
            
        y_indices = []
        for i in range(N):
            start = 1 + num_x_qubits + (i * BITS_PER_INT)
            y_indices.append(list(range(start, start + BITS_PER_INT)))
            
        self.build_oracle_mod_q(qc, pk, b_idx, x_indices, y_indices)
        
        # --- STATEVECTOR SIMULATION ---
        print(f"[Prover] Computing wavefunction (Total Qubits: {total_qubits})...")
        current_state = Statevector.from_instruction(qc)
        
        # Measure Y register
        y_qubits = list(range(1 + num_x_qubits, total_qubits))
        commitment_y, prover_state = current_state.measure(y_qubits)
        
        # Parse bits to int for display (Little Endian in Qiskit)
        # We just show the raw bitstring here for simplicity
        print(f"[Prover] Measured y (bits): {commitment_y}")
        
        return commitment_y, prover_state

    def step4_respond(self, prover_state, challenge):
        num_x_qubits = N * BITS_PER_INT
        current_state = prover_state
        
        if challenge == 1:
            print("[Prover] Challenge=1 (Hadamard). Rotating Basis...")
            qc_chal = QuantumCircuit(current_state.num_qubits)
            qc_chal.h(range(1 + num_x_qubits))
            current_state = current_state.evolve(qc_chal)
        else:
            print("[Prover] Challenge=0 (Standard).")

        # Measure Input Register
        input_qubits = list(range(1 + num_x_qubits))
        response, _ = current_state.measure(input_qubits)
        return response

class Verifier_Mahadev:
    def step1_setup(self):
        self.pk, self.sk = LWE_KeyGen.generate()
        print(f"[Verifier] Generated LWE Keys (Q={Q})")
        print(f"   > Trapdoor s: {self.sk['s']}")
        return self.pk, self.sk
    
    def step3_challenge(self):
        return secrets.choice([0, 1])

    def step5_verify(self, answer, pk, y, challenge, sk):
            """
            Verifies the Prover's response under the NO NOISE assumption.
            Calculations are exact modulo Q.
            """
            print(f"\n[Verifier] Verifying Response (Challenge c={challenge})...")
            
            # --- 1. PARSE THE ANSWER (b, x) ---
            # Qiskit returns little-endian strings (reversed). 
            ans_bits = answer[::-1] 
            
            b_val = int(ans_bits[0])
            
            # Parse x vector
            x_vec = []
            ptr = 1
            BITS_PER_INT = int(math.log2(Q)) 
            
            for _ in range(N):
                chunk = ans_bits[ptr : ptr + BITS_PER_INT]
                val = 0
                for idx, bit in enumerate(chunk):
                    if bit == '1': val += 2**idx
                x_vec.append(val)
                ptr += BITS_PER_INT
            
            x_vec = np.array(x_vec)
            print(f"   > Parsed: b={b_val}, x={x_vec}")

            # --- 2. VERIFICATION LOGIC ---
            
            if challenge == 0:
                # === TEST ROUND (Exact Match) ===
                # Logic: Check if Ax + bu == y (Exactly)
                
                # A. Calculate the expected y
                Ax = np.dot(pk['A'], x_vec)
                bu = b_val * pk['u']
                
                calculated_y = (Ax + bu) % Q
                
                # B. Parse the Prover's Commitment 'y'
                # y is the raw bitstring from the measurement
                y_bits = y[::-1]
                y_integers = []
                
                for i in range(N):
                    chunk = y_bits[i*BITS_PER_INT : (i+1)*BITS_PER_INT]
                    val = 0
                    for idx, bit in enumerate(chunk):
                        if bit == '1': val += 2**idx
                    y_integers.append(val)
                    
                print(f"   > Math Check: {calculated_y}")
                print(f"   > Commitment: {y_integers}")
                
                # C. STRICT EXACT COMPARISON
                # Numpy array comparison
                if np.array_equal(calculated_y, y_integers):
                    print("   > RESULT: PASS (Exact Match)")
                    return True, "Test Round Passed"
                else:
                    print("   > RESULT: FAIL (Mismatch)")
                    return False, "Test Round Failed"

            else:
                # === HADAMARD ROUND ===
                # Logic: d . s = b (mod 2)
                # This remains the same regardless of noise, provided the 
                # superposition was clean (which it is, since e=0).
                
                lhs = np.dot(x_vec, sk['s']) % 2
                rhs = b_val
                
                print(f"   > Trapdoor Check: {lhs} == {rhs}")
                
                if lhs == rhs:
                    print("   > RESULT: PASS (Trapdoor Relation Verified)")
                    return True, "Hadamard Round Passed"
                else:
                    print("   > RESULT: FAIL (Trapdoor Relation Violated)")
                    return False, "Hadamard Round Failed"

if __name__ == "__main__":
    verifier = Verifier_Mahadev()
    prover = Prover_Mahadev()
    
    pk, sk = verifier.step1_setup()
    y, state = prover.step2_commit(pk)
    
    c = verifier.step3_challenge()          # send y to V to trigger the challenge
    print(f"[Verifier] Challenge: {c}")
    
    ans = prover.step4_respond(state, c)
    verifier.step5_verify(ans, pk, y, c, sk)