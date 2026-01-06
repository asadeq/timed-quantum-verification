# This is our protocol

from qiskit import QuantumCircuit
from torch import rand
from cvqc_protocol.ccy_protocol import Verifier, Prover
from cvqc_protocol.hamiltonian_compiler import HamiltonianCompiler
from timelock_puzzle.tlp_lattice import TimeLockPuzzle
from utils import random_oracle

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

        # Run phase 1 of CCY
        ccy_verifier = Verifier()
        pk, sk = ccy_verifier.round1(hist_circuit, Q=16) 

        # TODO: Commitmment to the sk (use a hash function) why are we truncating???
        d = random_oracle(sk)

        # Generate puzzle
        puzzle = tlp.generate(pp, sk)

        return (pp, pk, puzzle, d)

    def prove(circuit):
        pass

    def reveal():
        pass

    def verify():
        pass
        
