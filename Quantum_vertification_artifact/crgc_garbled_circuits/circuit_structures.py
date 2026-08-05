"""
Core data structures for CRGC circuit processing
Matches C++ struct layouts for compatibility
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class CircuitDetails:
    """Circuit metadata matching C++ CircuitDetails struct"""
    numWires: int = 0
    numGates: int = 0
    numOutputs: int = 0
    bitlengthInputA: int = 0  # Generator's input
    bitlengthInputB: int = 0  # Evaluator's input
    bitlengthOutputs: int = 0


@dataclass
class TransformedGate:
    """
    Gate with 2x2 truth table
    Matches C++ Gate<bool[2][2]> struct
    
    truthTable[leftInput][rightInput] = output
    where leftInput, rightInput, output are boolean (0 or 1)
    """
    leftParentID: int = 0
    rightParentID: int = 0
    outputID: int = 0
    truthTable: List[List[bool]] = field(default_factory=lambda: [[False, False], [False, False]])
    
    def __post_init__(self):
        """Ensure truth table is 2x2"""
        if not isinstance(self.truthTable, list) or len(self.truthTable) != 2:
            self.truthTable = [[False, False], [False, False]]
        elif len(self.truthTable[0]) != 2 or len(self.truthTable[1]) != 2:
            self.truthTable = [[False, False], [False, False]]


class TransformedCircuit:
    """
    Circuit with transformed gates
    Matches C++ Circuit<TransformedGate> struct
    
    Wire indexing convention:
    - Wires 0 to bitlengthInputA-1: Generator's input (InputA)
    - Wires bitlengthInputA to bitlengthInputA+bitlengthInputB-1: Evaluator's input (InputB)
    - Wires bitlengthInputA+bitlengthInputB onwards: Gate outputs
    - Last numOutputs * bitlengthOutputs wires: Circuit outputs
    """
    def __init__(self, details: CircuitDetails = None):
        self.details = details if details else CircuitDetails()
        self.gates: List[TransformedGate] = []
    
    def add_gate(self, gate: TransformedGate):
        """Add a gate to the circuit"""
        self.gates.append(gate)
    
    def __len__(self):
        """Return number of gates"""
        return len(self.gates)
