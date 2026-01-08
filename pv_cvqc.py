# This is our protocol

from qiskit import QuantumCircuit
from torch import rand
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

    def setup(self, secp, circuit):
    
        compiler = HamiltonianCompiler(circuit)     # compile it to a Hamiltonian
        hist_circuit = compiler.compile()           

        # TODO: T will be the depth of hist_circuit (or some function of it)
        T = hist_circuit.depth()

        # Prepare the public parameters of the TLP
        self.tlp = TimeLockPuzzle(T=T)
        pp = self.tlp.setup()

        tlp2 = PythonGarbledTLP(T=T)
        pp2 = tlp2.PSetup_Garble()

        # Run phase 1 of CCY
        ccy_verifier = Verifier()
        pk, sk = ccy_verifier.round1(hist_circuit, Q=16) 

        # Hash the concatenation sk with random r of same length
        r = rand(secp // 8).numpy().tobytes()
        d = random_oracle(sk + r, output_length=secp // 8)

        # Generate puzzle
        puzzle = self.tlp.generate(pp, sk)

        puzzle2 = tlp2.PGen(1,pp2)

        # CRS
        crs = (pp, pk, puzzle, d)

        return crs, sk

    def prove(self, crs, circuit):

        (_, pk, _, d) = crs

        # Run round 2 of CCY
        ccy_prover = Prover()
        proof = ccy_prover.round2(circuit, pk)
        return proof

    def reveal(self, crs, circuit):

        (pp, _, puzzle, _) = crs

        # Solve the puzzle to get sk
        y = self.tlp.solve(pp, puzzle)

        return y

    def verify(self, crs, proof, y):

        (_, pk, _, d) = crs

        # Deconcatenate s to get sk and r
        secp = len(d) * 8
        sk = y[:-secp // 8]
        r = y[-secp // 8:]

        ccy_verifier = Verifier()   
        result = ccy_verifier.verify(pk, sk, proof)

        return result
        
# main
if __name__ == "__main__":
    
    circuit = QuantumCircuit(4)                         # The user circuit
    secp = 256
    pp, pk, puzzle, d = PV_CVQC.setup(secp, circuit)
    print("Public parameters:", pp)
    print("Public key:", pk)
    print("Puzzle:", puzzle)
    print("Commitment:", d) 

    proof = PV_CVQC.prove((pp, pk, puzzle, d), circuit)
    print("Proof:", proof)

    y = PV_CVQC.reveal((pp, pk, puzzle, d), circuit)
    print("Revealed secret:", y)

    result = PV_CVQC.verify((pp, pk, puzzle, d), proof, y)
    print("Verification result:", result)


        
