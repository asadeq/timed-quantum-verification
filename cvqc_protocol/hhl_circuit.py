import numpy as np
from scipy.linalg import expm
import math
from qiskit import QuantumCircuit, QuantumRegister
from qiskit.circuit.library import QFTGate, PauliEvolutionGate, UnitaryGate
from qiskit.quantum_info import SparsePauliOp
from hamiltonian_compiler import HamiltonianCompiler

class HHL_Builder:
    def __init__(self, matrix_A, vector_b, clock_qubits=3, evolution_time=2*np.pi):
        """
        Args:
            matrix_A (np.array): NxN Hermitian matrix (N must be power of 2).
            vector_b (np.array): N-dim vector.
            clock_qubits (int): Precision of eigenvalue estimation.
            evolution_time (float): Total evolution time 't' for e^{iAt}.
                                    Usually chosen so t < 2*pi / max(eigenvalue).
        """
        self.A = np.array(matrix_A)
        self.b = np.array(vector_b)
        self.n_b = int(math.log2(len(vector_b))) # Number of qubits for vector b
        self.n_clock = clock_qubits
        self.t = evolution_time
        
        # Validation
        if not np.allclose(self.A, self.A.conj().T):
            raise ValueError("Matrix A must be Hermitian.")
        
        # Registers
        self.q_clock = QuantumRegister(self.n_clock, 'clock')
        self.q_b = QuantumRegister(self.n_b, 'b')
        self.q_ancilla = QuantumRegister(1, 'ancilla')
        
        self.qc = QuantumCircuit(self.q_clock, self.q_b, self.q_ancilla)

    def step1_state_prep(self):
        """Loads vector b into the quantum register."""
        # Normalize b
        norm_b = self.b / np.linalg.norm(self.b)
        # Use Qiskit's built-in initializer (Isometry)
        self.qc.initialize(norm_b, self.q_b)

    def step2_qpe(self):
        """
        Generic QPE using Hamiltonian Simulation (e^{iAt}).
        For general A, we use PauliEvolutionGate.
        """
        self.qc.h(self.q_clock)
        
        # Create Operator for A
        # (Naive method: map matrix directly to Hamiltonian. 
        # For large N, decompose to Pauli sums manually.)
        op_A = SparsePauliOp.from_operator(self.A)
        
        # Apply Controlled-Unitaries
        # U = e^{i * A * t}
        # We apply U^{2^k} controlled on clock bit k
        
        for k in range(self.n_clock):
            time_step = self.t * (2 ** k)
            
            # Create e^{i * A * time_step}
            # Note: Qiskit's PauliEvolutionGate handles the Trotterization internally
            # or uses matrix exponentiation for small systems.
            evo_gate = PauliEvolutionGate(op_A, time=time_step)
            
            # Make it controlled
            # (PauliEvolutionGate doesn't support .control() directly in older Qiskit versions,
            # but usually MatrixExponential synthesis works).
            
            # Workaround for stability: synthesize unitary first
            unitary_matrix = expm(1j * self.A * time_step)
            
            # Create Controlled Gate from Matrix
            u_gate = UnitaryGate(unitary_matrix, label=f"U(2^{k})")
            c_u_gate = u_gate.control(1)
            
            self.qc.append(c_u_gate, [self.q_clock[k]] + list(self.q_b))

        # Inverse QFT
        self.qc.append(QFTGate(self.n_clock).inverse(), self.q_clock)

    def step3_rotation(self):
        """
        Performs rotation based on the integer value in Clock register.
        Angle theta ~ C / lambda.
        lambda is encoded in the integer value 'k' of the clock register.
        lambda_k = (2*pi * k) / (t * 2^n_clock)  [Roughly]
        """
        # We iterate through every possible integer 'k' the clock can hold.
        # If clock == k, we apply rotation R_y( theta_k ).
        
        max_int = 2 ** self.n_clock
        
        for k in range(1, max_int): # Skip 0 (eigenvalue 0 is non-invertible)
            
            # 1. Calculate Lambda corresponding to integer k
            # Phase phi = k / 2^n_clock
            # Eigenvalue lambda = phi * (2*pi / t) 
            # (Derivation depends on exact QPE convention)
            
            lam = (k / max_int) * (2 * np.pi / self.t)
            
            # 2. Calculate Rotation Angle
            # We want sin(theta) = C / lam. Let C = small constant (e.g., min lambda).
            C = 0.1 # Constant scaling factor
            ratio = C / lam
            if ratio > 1: ratio = 1
            if ratio < -1: ratio = -1
            
            theta = 2 * np.arcsin(ratio)
            
            # 3. Apply Controlled Rotation
            # Control condition: Clock == k
            bin_str = format(k, f'0{self.n_clock}b')
            
            # Note: Qiskit's mcry uses generic controls.
            # We need to wrap it to trigger on specific bitstring 'bin_str'.
            # Or use standard mcry and X-gates to wrap.
            
            # Wrap in X gates for 0s
            for idx, bit in enumerate(reversed(bin_str)): # Qiskit bit ordering
                if bit == '0':
                    self.qc.x(self.q_clock[idx])
                    
            # Apply Multi-Controlled RY
            self.qc.mcry(theta, self.q_clock, self.q_ancilla)
            
            # Unwrap X gates
            for idx, bit in enumerate(reversed(bin_str)):
                if bit == '0':
                    self.qc.x(self.q_clock[idx])

    def step4_inverse_qpe(self):
        """Uncompute QPE to clean up the clock register."""
        # 1. QFT
        self.qc.append(QFTGate(self.n_clock), self.q_clock)
        
        # 2. Inverse Hamiltonian Simulation
        for k in range(self.n_clock):
            time_step = self.t * (2 ** k)
            
            # We need e^{-i * A * time_step} (Inverse evolution)
            from scipy.linalg import expm
            from qiskit.circuit.library import UnitaryGate
            
            # Note the minus sign (-1j)
            unitary_matrix = expm(-1j * self.A * time_step)
            
            u_gate = UnitaryGate(unitary_matrix, label=f"U_inv(2^{k})")
            c_u_gate = u_gate.control(1)
            
            self.qc.append(c_u_gate, [self.q_clock[k]] + list(self.q_b))
            
        self.qc.h(self.q_clock)

    def build(self):
        self.step1_state_prep()
        self.qc.barrier()
        self.step2_qpe()
        self.qc.barrier()
        self.step3_rotation()
        self.qc.barrier()
        self.step4_inverse_qpe()
        return self.qc

# --- EXAMPLE USAGE ---
if __name__ == "__main__":
    # Define a 4x4 System (N=4)
    # A must be Hermitian.
    #A = np.diag([1, 2, 3, 4]) 
    #b = [1, 1, 1, 1]

    # Define a 2x2 System (N=2)
    A = np.diag([1, 2]) 
    b = [1, 0]
    
    # Instantiate Builder
    # Increase clock_qubits for better precision on 4 eigenvalues
    builder = HHL_Builder(A, b, clock_qubits=4, evolution_time=np.pi/4)
    
    # Build
    hhl_circuit = builder.build()

    # print Circuit
    #print("\n--- HHL Circuit ---")
    #print(hhl_circuit)
    
    print("--- HHL Circuit Stats ---")
    print(f"Matrix Size: {A.shape}")
    print(f"Qubits Used: {hhl_circuit.num_qubits}")
    print(f"Depth: {hhl_circuit.depth()}")
    
    #compiler = HamiltonianCompiler(hhl_circuit)
    #hist_qc = compiler.compile()
    #print("Compiled successfully!")