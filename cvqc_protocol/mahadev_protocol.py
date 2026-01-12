import numpy as np
import secrets
import math
from qiskit import QuantumCircuit
from qiskit.circuit.library import UnitaryGate
from qiskit.quantum_info import Statevector
from cvqc_protocol.hamiltonian_compiler import HamiltonianCompiler

class LWE:
    def __init__(self, circuit_qubits, Q):
        self.Q = Q
        self.bits_per_int = int(math.log2(Q))
        
        # Calculate N: We need N * bits >= circuit_qubits
        # N must be large enough to embed the whole history state as input 'x'
        self.N = math.ceil(circuit_qubits / self.bits_per_int)
        
        # Ensure N is at least 2
        if self.N < 2: 
            self.N = 2
            
        self.capacity = self.N * self.bits_per_int
        
        print(f"(Config) -- Circuit Size: {circuit_qubits} qubits")
        print(f"(Config) -- LWE Parameters: N={self.N}, Q={self.Q} ({self.bits_per_int} bits/int)")
        print(f"(Config) -- Total Capacity: {self.capacity} bits")
    
    # Generate LWE Keys
    def generate(self):

        Q = self.Q
        N = self.N
        
        # Generate keys using the passed dimensions
        s = np.random.randint(0, Q, size=N)
        A = np.random.randint(0, Q, size=(N, N))
        e = np.zeros(N, dtype=int) # No noise for simulation
        u = (np.dot(A, s) + e) % Q
        
    
        pk = {'A': A, 'u': u, 'Q': Q, 'N': N}
        sk = {'s': s, 'Q': Q, 'N': N}
        
        return pk, sk

class QuantumAdder:
    """
    A generic arithmetic unit that works for any Modulo Q that is a power of 2.
    It builds the unitary matrix for 'x + C mod Q' and applies it.
    """
    # @staticmethod
    # def get_add_gate(const_val, num_qubits):
    #     """
    #     Creates a Quantum Gate that performs: |y> -> |(y + const_val) % Q>
    #     """
    #     dim = 2 ** num_qubits
    #     matrix = np.zeros((dim, dim))
        
    #     # Build the permutation matrix for addition mod 2^k
    #     for i in range(dim):
    #         target = (i + const_val) % dim
    #         matrix[target, i] = 1.0
            
    #     # Create a Qiskit Gate from this matrix
    #     gate = UnitaryGate(matrix, label=f"Add({const_val})")
    #     return gate

    @staticmethod
    def add_const_controlled(qc, ctrl_qubit, target_qubits, val, Q):
        """
        Applies Controlled-Add(val).
        If ctrl_qubit is 1, add 'val' to target_qubits (modulo Q).
        """
        val = val % Q
        if val == 0: return

        # OLD IMPLEMENTATION (caused Rust panic during synthesis):
        # add_gate = QuantumAdder.get_add_gate(val, len(target_qubits))
        # c_add_gate = add_gate.control(1)
        # qc.append(c_add_gate, [ctrl_qubit] + target_qubits)
        
        # Manually construct controlled-unitary matrix
        num_target_qubits = len(target_qubits)
        dim_target = 2 ** num_target_qubits
        
        # Build controlled-unitary matrix manually
        # Control qubit dimension is 2, target dimension is dim_target
        # Total dimension is 2 * dim_target
        total_dim = 2 * dim_target
        c_matrix = np.eye(total_dim, dtype=complex)
        
        # When control = 1 (second half of the matrix), apply the addition
        for i in range(dim_target):
            target = (i + val) % dim_target
            # Set the controlled portion (bottom-right block)
            c_matrix[dim_target + i, dim_target + i] = 0
            c_matrix[dim_target + target, dim_target + i] = 1
        
        # Create controlled gate
        c_add_gate = UnitaryGate(c_matrix, label=f"C-Add({val})")
        
        # Append to circuit: [list of target bits] + [ctrl_bit]
        qc.append(c_add_gate, target_qubits + [ctrl_qubit])

class ProverMahadev:
    def __init__(self):
        pass

    # Used to build clawfree TDF circuit which will be applied coherently
    def build_clawfree_tdf_circuit(self, qc, pk, b_idx, x_indices, y_indices):
       
        A = pk['A']
        u = pk['u']
        N = pk['N']
        Q = pk['Q']

        # The clawfree function used is f(b, x) = Ax + bu (Mod Q)
        # This is only true for e=0 (no noise). See [BCM+18]. 
        
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
                    QuantumAdder.add_const_controlled(qc, ctrl_qubit, y_indices[i], scalar, Q)

        # 2. Add bu (Mod Q)
        for i in range(N):
            scalar = u[i]
            QuantumAdder.add_const_controlled(qc, b_idx, y_indices[i], scalar, Q)

    def step2_commit(self, pk, hist_circuit):
        """
        Args:
            pk: Public Key (A, u)
            history_circuit: The QuantumCircuit output from HamiltonianCompiler
        """

        N = pk['N']
        Q = pk['Q']
        BITS_PER_INT = int(math.log2(Q))

        print(f"(P2) -- Initializing Quantum Memory for Q={Q}...")

        #num_x_qubits = N * BITS_PER_INT
        # The history state acts as the input 'x' to the LWE function.
        num_x_qubits = hist_circuit.num_qubits
        num_y_qubits = N * BITS_PER_INT
        total_qubits = 1 + num_x_qubits + num_y_qubits
        
        max_capacity = N * BITS_PER_INT
        if num_x_qubits > max_capacity:
            raise ValueError(f"LWE Key is too small! Key supports {max_capacity} qubits, but circuit needs {num_x_qubits}.")

        # Structure: [b (1)] + [x (History)] + [y (Commitment)]
        num_y_qubits = max_capacity # y must match x capacity in LWE
        total_qubits = 1 + max_capacity + num_y_qubits

        qc = QuantumCircuit(total_qubits)

        # Initialize b qubit in superposition
        qc.h(0)

        # Paste the hist_circuit into the 'x' register.
        # 'x' starts at qubit 1 (qubit 0 is 'b').
        
        # We map hist_circuit[0] -> qc[1]
        # We map hist_circuit[1] -> qc[2] ...
        qubit_map = list(range(1, 1 + num_x_qubits))
        
        qc.compose(hist_circuit, qubits=qubit_map, inplace=True)
        
        # Note: If max_capacity > num_x_qubits, the remaining x qubits 
        # stay at |0>. This effectively pads the vector x with zeros.
        
        # 2. Oracle
        b_idx = 0

        # Need to tell the Oracle where to find x and y
        x_indices = []
        for i in range(N):
            start = 1 + (i * BITS_PER_INT)
            x_indices.append(list(range(start, start + BITS_PER_INT)))
            
        y_indices = []
        for i in range(N):
            start = 1 + max_capacity + (i * BITS_PER_INT)
            y_indices.append(list(range(start, start + BITS_PER_INT)))
            
        self.build_clawfree_tdf_circuit(qc, pk, b_idx, x_indices, y_indices)
        
        # STATEVECTOR SIMULATION
        print(f"(P2) -- Simulating Full State (Qubits: {total_qubits})...")
        state = Statevector.from_instruction(qc)
        
        # Measure Y register
        y_qubits = list(range(1 + max_capacity, total_qubits))
        commitment_y, prover_state = state.measure(y_qubits)
        
        # Parse bits to int for display (Little Endian in Qiskit)
        # Show the raw bitstring here for simplicity
        print(f"(P2) -- Measured y (bits): {commitment_y}")
        
        return commitment_y, prover_state

    def step4_respond(self, prover_state, challenge):
        
        total_qubits = prover_state.num_qubits
        num_y = (total_qubits - 1) // 2
        
        if challenge == 1:
            print("(P4) -- Received c = 1 (Hadamard). Rotating Basis...")
            num_x = num_y
            qc = QuantumCircuit(total_qubits)
            qc.h(range(0,1 + num_x))
            prover_state = prover_state.evolve(qc)
        else:
            print("(P4) -- Received c = 0 (Standard).")

        # Measure Input (b + x)
        # We measure EVERYTHING except the Y register (which was already measured)
        # Actually, standard protocol measures b + x.
        input_range = range(0, 1 + num_y)
        response, _ = prover_state.measure(list(input_range))
        return response

class VerifierMahadev:
    
    def step1_setup(self, hist_circuit, Q):

        circuit_size = hist_circuit.num_qubits

        # h[i] = 0 corresponds to Z-basis (Standard)
        # h[i] = 1 corresponds to X-basis (Hadamard)
        #self.h = np.random.randint(0, 2, size=circuit_size)
        #print(f"(V1) -- Selected Hamiltonian Basis h: {self.h}")

        lwe = LWE(circuit_size, Q)        
        self.pk, self.sk = lwe.generate()
        print(f"(V1) -- Generated LWE Keys (Q={Q})")
        print(f"   > Trapdoor s: {self.sk['s']}")
        return self.pk, self.sk
    
    def step3_challenge(self):

        c = secrets.choice([0, 1])
        print(f"(V3) -- Generated Random Challenge: c = {c}")
        return c

    def step5_verify(self, pk, sk, y, c, a):
            """
            Verifies the Prover's response
            """
            print(f"(Vout) -- Verifying Response (Challenge c = {c})...")
            N = pk['N']
            Q = pk['Q']
            
            # --- 1. PARSE THE ANSWER (b, x) ---
            # Qiskit returns little-endian strings (reversed). 
            ans_bits = a[::-1] 
            
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
            
            if c == 0:
                # === TEST ROUND ===
                # Logic: Check if Ax + bu == y
                
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
                    
                print(f"   > Check: {calculated_y}")
                print(f"   > Commitment: {y_integers}")
                
                # C. Numpy array comparison
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
    
    verifier = VerifierMahadev()
    prover = ProverMahadev()
    
    hhl_circuit = QuantumCircuit(4)         ## This would be replaced with the actual HHL circuit
    hhl_circuit.h(0)
    hhl_circuit.cx(0,1)
    
    compiler = HamiltonianCompiler(hhl_circuit)
    hist_circuit = compiler.compile()       # Generate the Feynman-Kitaev history state circuit for the user circuit

    Q = 4                                    # LWE Modulus

    pk, sk = verifier.step1_setup(hist_circuit, Q)
    y, state = prover.step2_commit(pk, hist_circuit)
    c = verifier.step3_challenge()          # send y to V to trigger the challenge
    #c=1 (testing)
    ans = prover.step4_respond(state, c)
    verifier.step5_verify(pk, sk, y, c, ans)