"""
Input obfuscation and circuit flipping for CRGC
Transforms circuit truth tables based on input obfuscation
"""

from typing import List, Tuple
from .circuit_structures import TransformedCircuit
from .helper_functions import generate_random_bool, swap_left_parent, swap_right_parent, flip_table


def obfuscate_input(inputA: List[bool], num_wires: int) -> Tuple[List[bool], List[bool]]:
    """
    Generate obfuscated input and track flipped wires
    
    Args:
        inputA: Original generator input
        num_wires: Total number of wires in circuit
    
    Returns:
        Tuple of (obfuscated_val_arr, flipped)
    """
    obfuscated_val_arr = [generate_random_bool() for _ in range(len(inputA))]
    flipped = [False] * num_wires
    
    # Track which input wires are flipped
    for i in range(len(inputA)):
        flipped[len(inputA) - 1 - i] = (obfuscated_val_arr[i] != inputA[i])
    
    return obfuscated_val_arr, flipped


def get_flipped_circuit(circuit: TransformedCircuit, flipped: List[bool]) -> None:
    """
    Flip circuit truth tables based on parent wire flips
    
    Modifies circuit gates in place:
    1. Recover integrity from parent flips
    2. Randomly flip outputs (except circuit outputs)
    
    Args:
        circuit: Transformed circuit (modified in place)
        flipped: Flipped wire tracking array (modified in place)
    """
    # Output wire range (cannot flip these)
    output_start = circuit.details.numWires - circuit.details.numOutputs * circuit.details.bitlengthOutputs
    
    for gate in circuit.gates:
        # Recover integrity from parent flips
        if flipped[gate.leftParentID]:
            swap_left_parent(gate.truthTable)
        
        if flipped[gate.rightParentID]:
            swap_right_parent(gate.truthTable)
        
        # Randomly flip output (except for circuit output wires)
        if gate.outputID < output_start:
            if generate_random_bool():
                flip_table(gate.truthTable)
                flipped[gate.outputID] = True
            else:
                flipped[gate.outputID] = False  # Reset if not flipped!
