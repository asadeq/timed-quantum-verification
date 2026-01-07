"""
Circuit evaluator for CRGC
Evaluates transformed circuits on given inputs
"""

from typing import List
from .circuit_structures import TransformedCircuit


def evaluate_transformed_circuit(circuit: TransformedCircuit, inputA: List[bool], inputB: List[bool]) -> List[bool]:
    """
    Evaluate transformed circuit on given inputs
    
    CRITICAL: Input and output bits are REVERSED for C++ compatibility
    
    Args:
        circuit: Transformed circuit to evaluate
        inputA: Generator's input (bool array)
        inputB: Evaluator's input (bool array)
    
    Returns:
        Circuit output (bool array)
    """
    evaluation = [False] * circuit.details.numWires
    
    # Load InputA (REVERSED for C++ compatibility)
    for i in range(circuit.details.bitlengthInputA):
        evaluation[i] = inputA[circuit.details.bitlengthInputA - 1 - i]
    
    # Load InputB (REVERSED for C++ compatibility)
    for i in range(circuit.details.bitlengthInputB):
        evaluation[i + circuit.details.bitlengthInputA] = inputB[circuit.details.bitlengthInputB - 1 - i]
    
    # Evaluate gates
    for gate in circuit.gates:
        left_val = int(evaluation[gate.leftParentID])
        right_val = int(evaluation[gate.rightParentID])
        evaluation[gate.outputID] = gate.truthTable[left_val][right_val]
    
    # Extract outputs (REVERSED for C++ compatibility)
    output = []
    for i in range(circuit.details.numOutputs):
        for j in range(circuit.details.bitlengthOutputs):
            wire_idx = circuit.details.numWires - 1 - j - circuit.details.bitlengthOutputs * i
            output.append(evaluation[wire_idx])
    
    return output


def evaluate_sorted_transformed_circuit(circuit: TransformedCircuit, inputA: List[bool], inputB: List[bool]) -> List[bool]:
    """
    Evaluate sorted transformed circuit (optimized for EMP format)
    
    For sorted circuits where gate outputID = gate_index + bitlengthInputA + bitlengthInputB,
    we can use direct indexing for better performance.
    
    Args:
        circuit: Sorted transformed circuit
        inputA: Generator's input (bool array)
        inputB: Evaluator's input (bool array)
    
    Returns:
        Circuit output (bool array)
    """
    evaluation = [False] * circuit.details.numWires
    
    # Load InputA (REVERSED)
    for i in range(circuit.details.bitlengthInputA):
        evaluation[i] = inputA[circuit.details.bitlengthInputA - 1 - i]
    
    # Load InputB (REVERSED)
    for i in range(circuit.details.bitlengthInputB):
        evaluation[i + circuit.details.bitlengthInputA] = inputB[circuit.details.bitlengthInputB - 1 - i]
    
    # Evaluate gates with direct indexing
    for i, gate in enumerate(circuit.gates):
        left_val = int(evaluation[gate.leftParentID])
        right_val = int(evaluation[gate.rightParentID])
        evaluation[i + circuit.details.bitlengthInputA + circuit.details.bitlengthInputB] = \
            gate.truthTable[left_val][right_val]
    
    # Extract outputs (REVERSED)
    output = []
    for i in range(circuit.details.numOutputs):
        for j in range(circuit.details.bitlengthOutputs):
            wire_idx = circuit.details.numWires - 1 - j - circuit.details.bitlengthOutputs * i
            output.append(evaluation[wire_idx])
    
    return output


# Optional numpy-accelerated version
try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


def evaluate_transformed_circuit_numpy(circuit: TransformedCircuit, inputA: List[bool], inputB: List[bool]) -> List[bool]:
    """
    Numpy-accelerated circuit evaluation (optional)
    
    Args:
        circuit: Transformed circuit to evaluate
        inputA: Generator's input (bool array)
        inputB: Evaluator's input (bool array)
    
    Returns:
        Circuit output (bool array)
    """
    if not NUMPY_AVAILABLE:
        raise ImportError("Numpy not available, use evaluate_transformed_circuit instead")
    
    evaluation = np.zeros(circuit.details.numWires, dtype=bool)
    
    # Load inputs (REVERSED)
    for i in range(circuit.details.bitlengthInputA):
        evaluation[i] = inputA[circuit.details.bitlengthInputA - 1 - i]
    
    for i in range(circuit.details.bitlengthInputB):
        evaluation[i + circuit.details.bitlengthInputA] = inputB[circuit.details.bitlengthInputB - 1 - i]
    
    # Evaluate gates
    for gate in circuit.gates:
        left_val = int(evaluation[gate.leftParentID])
        right_val = int(evaluation[gate.rightParentID])
        evaluation[gate.outputID] = gate.truthTable[left_val][right_val]
    
    # Extract outputs (REVERSED)
    output = []
    for i in range(circuit.details.numOutputs):
        for j in range(circuit.details.bitlengthOutputs):
            wire_idx = circuit.details.numWires - 1 - j - circuit.details.bitlengthOutputs * i
            output.append(bool(evaluation[wire_idx]))
    
    return output
