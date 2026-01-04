import hashlib
import secrets
from mahadev_protocol import Prover_Mahadev, Verifier_Mahadev

def random_oracle(y, m):
    """
    The Idealized Hash Function H.
    Set c := H(y) 
    """
    # Create a deterministic hash of the commitment y
    h = hashlib.sha256(y.encode('utf-8')).hexdigest()
    
    # Convert hex hash to a binary string of length m (the challenge string)
    # We take the integer value and format it as binary.
    binary_c = bin(int(h, 16))[2:].zfill(256) 
    
    # Truncate or pad to exactly length m
    return binary_c[:m]

class MahadevAbstractions:
    """
    Abstract representations of the underlying m-parallel Mahadev protocol components.
    In the paper, these represent the parallel repetition of the 4-round protocol 
    components described in Section 3.1 and 3.2.
    """

    # Global variables to simulate the Mahadev protocol actors
    _verifier = Verifier_Mahadev()
    _prover = Prover_Mahadev()
    
    @staticmethod
    def V1():
        """
        Represents the m-parallel V1 generation algorithm.
        Source: "The verifier runs V1 to generate (k, td)." 
        """
        # In a real quantum implementation, this generates LWE keys and trapdoors.
        # We simulate this by returning unique tokens.
        # k = f"key_{secrets.token_hex(4)}"
        # td = f"trapdoor_{secrets.token_hex(4)}"

        k, td = MahadevAbstractions._verifier.step1_setup()          
        return k, td

    @staticmethod
    def P2(k):
        """
        Represents the m-parallel P2 algorithm.
        Source: "The prover runs P2 on input k to generate y along with the 
        prover's state |st_P>." 
        """
        # # 'y' is a classical commitment.
        # y = f"commitment_{secrets.token_hex(4)}"
        # # 'st_P' is actually a quantum state (qubits). We represent it as a placeholder.
        # st_P = "quantum_state_placeholder" 

        y, st_P = MahadevAbstractions._prover.step2_commit(k)

        return y, st_P
    
    @staticmethod
    def V3():
        """
        Randomly pick a challenge c and send it to the prover.
        """
        # In the non-interactive version, c is derived from y using a hash function.
        # Here, we just return random bit c
        #c = secrets.token_hex(1)

        c = MahadevAbstractions._verifier.step3_challenge()

        return c

    @staticmethod
    def P4(st_P, c):
        """
        Represents the m-parallel P4 algorithm.
        """
        a = MahadevAbstractions._prover.step4_respond(st_P, c)
        return a

    @staticmethod
    def V_out(k, td, y, c, a):
        """
        Represents the m-parallel final verification step.
        Source: "runs V_out(k, td, y, c, a), and outputs as V_out outputs." 
        """
        return MahadevAbstractions._verifier.step5_verify(a, k, y, c, td)

class Verifier:
    def __init__(self, security_param, m):
        self.n = security_param
        self.m = m # Number of parallel repetitions
        self.td = None # Internal state to keep trapdoor 

    def round1(self, problem_instance_x):
        """
        First Message: The verifier runs V1 to generate (k, td).
        """
        self.k, self.td = MahadevAbstractions.V1()

        # "Sends k to the prover and keeps td as its state."
        return self.k

    def verify(self, proof_tuple):
        """
        Verification: The verifier computes c = H(y), runs V_out... 
        """
        y, a = proof_tuple
        
        # Recompute the challenge c using the random oracle H(y)
        c = random_oracle(y, self.m)
        
        print(f"[Verifier] Computed challenge c = H(y): {c}")
        
        # Run the underlying Mahadev verification
        result = MahadevAbstractions.V_out(self.k, self.td, y, c, a)
        
        if result:
            return "Accept" 
        else:
            return "Reject"

class Prover:
    def __init__(self, problem_instance_x, m):
        self.x = problem_instance_x
        self.m = m

    def round2(self, k):
        """
        Second Message: 
        1. Run P2 to get y and |st_P>
        2. Set c := H(y)
        3. Run P4 to get a
        4. Return (y, a)
        """
        # 1. Generate commitment y and quantum state |st_P> 
        y, st_P = MahadevAbstractions.P2(k)
        
        # 2. Apply the Fiat-Shamir transform: c = H(y) 
        # Ideally this is a Quantum Random Oracle, but we simulate the classical hash.
        c = random_oracle(y, self.m)
        print(f"[Prover] Computed internal challenge c = H(y): {c}")

        # 3. Generate answer a using the state and the derived challenge 
        a = MahadevAbstractions.P4(st_P, c)

        # 4. Returns (y, a) to the verifier 
        return (y, a)

# --- Execution Simulation ---

def run_protocol():
    print("--- Simulating Two-Round CVQC ---")
    
    # Configuration
    security_param = 128
    m = 10 # Number of parallel repetitions
    problem_instance_x = "Problem_Instance_X" # The BQP language instance
    
    # Initialize Actors
    verifier = Verifier(security_param, m)
    prover = Prover(problem_instance_x, m)

    # Round 1: Verifier -> Prover
    print("\n1. Verifier generates keys...")
    k = verifier.round1(problem_instance_x)
    print(f"Round 1: Verifier sends key: {k}")

    # Round 2: Prover -> Verifier
    # The prover computes y, derives c = H(y), and computes a locally.
    print("\n2. Prover computes response (non-interactive challenge)...")
    proof = prover.round2(k)
    print(f"Round 2: Prover sends proof (y, a): {proof}")

    # Verification
    print("\n3. Verifier verifies the proof...")
    result = verifier.verify(proof)
    print(f"Result: {result}")

if __name__ == "__main__":
    run_protocol()