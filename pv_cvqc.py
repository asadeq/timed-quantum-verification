# This is our protocol

from qiskit import QuantumCircuit
import secrets
import time
from cvqc_protocol.ccy_protocol import Verifier, Prover
from cvqc_protocol.hamiltonian_compiler import HamiltonianCompiler
from timelock_puzzle.tlp_lattice import TimeLockPuzzle
from utils import random_oracle
from timelock_puzzle.tlp_garbling import PythonGarbledTLP

class PV_CVQC:
    """
    Implements our publicly verifiable CVQC protocol using the 2-round CCY protocol and the TLP
    """

    def __init__(self):
        self.tlp = None
        self.tlp2 = None

        #time stuff
        self.setup_time = 0
        self.garbling_time = 0
        self.generation_time = 0
        self.prove_time = 0
        self.reveal_time = 0
        self.verify_time = 0

    def setup(self, secp, circuit, testing_T=None):
        setup_start = time.perf_counter()
        
        compiler = HamiltonianCompiler(circuit)     # compile it to a Hamiltonian
        hist_circuit = compiler.compile()           

        # TODO: T will be the depth of hist_circuit (or some function of it)
        # If testing_T is provided, use it instead of calculating from circuit depth
        if testing_T is not None:
            T = testing_T
            print(f"[Setup] Using testing T = {T} for TLP")
        else:
            T = hist_circuit.depth()
            print(f"[Setup] Using T = {T} for TLP (from circuit depth)")
        # Prepare the public parameters of the TLP
        # self.tlp = TimeLockPuzzle(T=T)
        # pp = self.tlp.setup()

        # Timer for garbling setup
        garbling_start = time.perf_counter()
        self.tlp2 = PythonGarbledTLP(T=T)
        pp2 = self.tlp2.PSetup_Garble()
        self.garbling_time = time.perf_counter() - garbling_start
        print(f"[Timer] Garbling setup: {self.garbling_time:.4f}s")

        # Run phase 1 of CCY
        ccy_verifier = Verifier()
        pk, sk = ccy_verifier.round1(hist_circuit, Q=16) 

        # Hash the concatenation sk with random r of same length
        r = secrets.token_bytes(secp // 8)
        d = random_oracle(str(sk["s"]) + str(int.from_bytes(r, "big")), secp // 8)

        # Timer for puzzle generation
        generation_start = time.perf_counter()
        # Generate puzzle
        # s_bit = int(sum(sk["s"])) % 2
        # puzzle = self.tlp.generate(pp, s_bit)
        puzzle2 = self.tlp2.PGen(sk["s"],pp2)
        self.generation_time = time.perf_counter() - generation_start
        print(f"[Timer] Puzzle generation: {self.generation_time:.4f}s")

        # CRS
        crs = (pp2, pk, puzzle2, d)

        self.setup_time = time.perf_counter() - setup_start
        print(f"[Timer] Total setup: {self.setup_time:.4f}s")
        
        return crs, sk

    def prove(self, crs, circuit):
        prove_start = time.perf_counter()
        
        (_, pk, _, d) = crs

        # Run round 2 of CCY
        ccy_prover = Prover()
        proof = ccy_prover.round2(circuit, pk)
        
        self.prove_time = time.perf_counter() - prove_start
        print(f"[Timer] Prove: {self.prove_time:.4f}s")
        
        return proof

    def reveal(self, crs, circuit):
        reveal_start = time.perf_counter()
        
        (pp, _, puzzle, _) = crs

        # Solve the puzzle to get sk
        # y = self.tlp.solve(pp, puzzle)
        y = self.tlp2.PSolve(puzzle, pp)

        self.reveal_time = time.perf_counter() - reveal_start
        print(f"[Timer] Reveal: {self.reveal_time:.4f}s")
        
        return y

    def verify(self, crs, proof, y):
        verify_start = time.perf_counter()
        
        (_, pk, _, d) = crs

        # Reconstruct sk dictionary from revealed secret key array
        sk = {'s': y, 'Q': pk['Q'], 'N': pk['N']}

        ccy_verifier = Verifier()   
        result = ccy_verifier.verify(pk, sk, proof)

        self.verify_time = time.perf_counter() - verify_start
        print(f"[Timer] Verify: {self.verify_time:.4f}s")
        
        return result
        
# main
if __name__ == "__main__":
    
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)                 

    secp = 256
    protocol = PV_CVQC()
    crs, sk = protocol.setup(secp,circuit)
    pp, pk, puzzle, d = crs
    print("Public parameters:", pp)
    print("Public key:", pk)
    print("Puzzle:", puzzle)
    print("Commitment:", d) 

    proof = protocol.prove((pp, pk, puzzle, d), circuit)
    print("Proof:", proof)

    y = protocol.reveal((pp, pk, puzzle, d), circuit)
    print("Revealed secret:", y)

    result = protocol.verify((pp, pk, puzzle, d), proof, y)
    print("Verification result:", result)

    # Print timing summary
    print("\n" + "="*50)
    print("TIMING SUMMARY")
    print("="*50)
    print(f"Setup Phase:")
    print(f"  - Garbling setup:     {protocol.garbling_time:.4f}s")
    print(f"  - Puzzle generation:  {protocol.generation_time:.4f}s")
    print(f"  - Total setup:        {protocol.setup_time:.4f}s")
    print(f"Prove Phase:            {protocol.prove_time:.4f}s")
    print(f"Reveal Phase:           {protocol.reveal_time:.4f}s")
    print(f"Verify Phase:           {protocol.verify_time:.4f}s")
    print(f"Total Time:             {protocol.setup_time + protocol.prove_time + protocol.reveal_time + protocol.verify_time:.4f}s")
    print("="*50)

    result = protocol.verify((pp, pk, puzzle, d), proof, y)
    print("Verification result:", result)


        
