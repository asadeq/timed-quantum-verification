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
    def setup(secp, circuit):
        
        circuit = QuantumCircuit(4)                 # this is the true structure of the circuit we want to verify (would be provided the user e.g. hhl_circuit)
        compiler = HamiltonianCompiler(circuit)     # compile it to a Hamiltonian
        hist_circuit = compiler.compile()           

        # TODO: T will be the depth of hist_circuit (or some function of it)
        T = hist_circuit.depth()

        # Prepare the public parameters of the TLP
        tlp = TimeLockPuzzle(T=T)
        pp = tlp.setup()

        tlp2 = PythonGarbledTLP(T=T)
        pp2 = tlp2.PSetup_Garble()

        # Run phase 1 of CCY
        ccy_verifier = Verifier()
        pk, sk = ccy_verifier.round1(hist_circuit, Q=16) 

        # Hash the concatenation sk with random r of same length
        r = rand(secp // 8).numpy().tobytes()
        d = random_oracle(sk + r, output_length=secp // 8)

        # Generate puzzle
        puzzle = tlp.generate(pp, sk)

        puzzle2 = tlp2.PGen(1,pp2)

        # CRS
        crs = (pp, pk, puzzle, d)

        return crs, sk

    def prove(crs, circuit):

        (pp, pk, puzzle, d) = crs

        # Run round 2 of CCY
        ccy_prover = Prover()
        proof = ccy_prover.round2(circuit, pk)
        return proof

    def reveal(crs, circuit):

        (pp, _, puzzle, _) = crs

        # Solve the puzzle to get sk
        tlp = TimeLockPuzzle(T=puzzle.T)
        y = tlp.solve(pp, puzzle)

        return y

    def verify(crs, proof, y):

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
    circuit = QuantumCircuit(4)
    secp = 128
    pp, pk, puzzle, d = PV_CVQC.setup(secp, circuit)
    print("Public parameters:", pp)
    print("Public key:", pk)
    print("Puzzle:", puzzle)
    print("Commitment:", d) 
        
