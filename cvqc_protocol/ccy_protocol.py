from utils import random_oracle
from qiskit import QuantumCircuit
from .hamiltonian_compiler import HamiltonianCompiler
from .mahadev_protocol import ProverMahadev, VerifierMahadev

class Verifier:

    def __init__(self, m=5):
        self.VerMahadev = VerifierMahadev()
        self.m = m  # parallel repetitions

    def round1(self, hist_circuit, Q):
        """
        First Message: The verifier runs V1 to generate (k, td).
        """
        self.k, self.td = self.VerMahadev.step1_setup(hist_circuit, Q)

        # "Sends k to the prover and keeps td as its state."
        return self.k, self.td

    def verify(self, k, td, proof_tuple):
        """
        Verification: The verifier computes c = H(y), then runs V_out 
        """
        y, a = proof_tuple
        
        # Recompute the challenge c using the random oracle H(y)
        c = random_oracle(y, self.m)
        
        print(f"[Verifier] Computed challenge c = H(y): {c}")
        
        (passed, output) = self.VerMahadev.step5_verify(k, td, y, c, a)
        
        if passed:
            return f"Accept- {output}" 
        else:
            return f"Reject - {output}"

class Prover:
    def __init__(self, m=5):
        self.m = m
        self.ProMahadev = ProverMahadev()

    def round2(self, hist_circuit, k):
        """
        Second Message: 
        1. Run P2 to get y and |st_P>
        2. Set c := H(y)
        3. Run P4 to get a
        4. Return (y, a)
        """
        # 1. Generate commitment y and quantum state |st_P> 
        y, st_P = self.ProMahadev.step2_commit(k, hist_circuit)
        
        # 2. Apply the Fiat-Shamir transform: c = H(y) 
        # Ideally this is a Quantum Random Oracle, but we simulate the classical hash.
        c = random_oracle(y, self.m)
        print(f"[Prover] Computed internal challenge c = H(y): {c}")

        # 3. Generate answer a using the state and the derived challenge 
        a = self.ProMahadev.step4_respond(st_P, c)

        # 4. Returns (y, a) to the verifier 
        return (y, a)

# --- Execution Simulation ---

def run_protocol():
    print("--- Simulating Two-Round CVQC ---")
    
    # Configuration
    security_param = 128
    m = 10 # Number of parallel repetitions
    
    hhl_circuit = QuantumCircuit(4)         ## This would be replaced with the actual HHL circuit
    hhl_circuit.h(0)
    hhl_circuit.cx(0,1)
    compiler = HamiltonianCompiler(hhl_circuit)
    hist_circuit = compiler.compile()
    
    # Initialize Verifier and Prover
    verifier = Verifier()
    prover = Prover()

    # Round 1: Verifier -> Prover
    print("\n1. Verifier generates keys...")
    k, td = verifier.round1(hist_circuit, Q=16)
    print(f"Round 1: Verifier sends key: {k}")

    # Round 2: Prover -> Verifier
    # The prover computes y, derives c = H(y), and computes a locally.
    print("\n2. Prover computes response (non-interactive challenge)...")
    proof = prover.round2(hist_circuit, k)
    print(f"Round 2: Prover sends proof (y, a): {proof}")

    # Verification
    print("\n3. Verifier verifies the proof...")
    result = verifier.verify(k, td, proof)
    print(f"Result: {result}")

if __name__ == "__main__":
    run_protocol()