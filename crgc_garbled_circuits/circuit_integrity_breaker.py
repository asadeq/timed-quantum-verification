"""
Circuit integrity breaking and gate regeneration for CRGC
Identifies intermediary gates and regenerates obfuscated truth tables
"""

from typing import List
from collections import deque
from .circuit_structures import TransformedCircuit, CircuitDetails
from .helper_functions import generate_random_bool


def get_intermediary_gates_from_output(details: CircuitDetails, is_obfuscated: List[bool], parents: List[List[int]]) -> None:
    """
    Identify intermediary gates (on path from non-obfuscated gates to outputs)
    
    Uses backward BFS from output wires. Gates on path from non-obfuscated gates
    to outputs must also be obfuscated to prevent leakage.
    
    Args:
        details: Circuit metadata
        is_obfuscated: Obfuscated wire array (modified in place)
        parents: Parent tracking array
    """
    not_obfuscated = [False] * details.numWires
    queue = deque()
    added = [False] * details.numWires
    
    # Start from output wires
    for i in range(details.numOutputs):
        for j in range(details.bitlengthOutputs):
            wire_idx = details.numWires - 1 - j - details.bitlengthOutputs * i
            queue.append(wire_idx)
            added[wire_idx] = True
    
    # BFS backward through parents
    while queue:
        wire = queue.popleft()
        not_obfuscated[wire] = True
        
        for parent in parents[wire]:
            # Only traverse through gate wires (not input wires)
            if parent >= details.bitlengthInputA + details.bitlengthInputB:
                if not is_obfuscated[parent] and not added[parent]:
                    queue.append(parent)
                    added[parent] = True
    
    # Invert for gate wires - gates NOT on path to outputs are obfuscated
    output_start = details.numWires - details.numOutputs * details.bitlengthOutputs
    for wire in range(details.bitlengthInputA + details.bitlengthInputB, details.numWires):
        if wire < output_start:  # Not an output wire
            is_obfuscated[wire] = not not_obfuscated[wire]


def is_level_1_gate(circuit: TransformedCircuit, gate) -> bool:
    """
    Check if gate is level-1 (has input wire as parent)
    
    Args:
        circuit: Transformed circuit
        gate: Gate to check
    
    Returns:
        True if gate has input wire as parent
    """
    total_inputs = circuit.details.bitlengthInputA + circuit.details.bitlengthInputB
    return gate.leftParentID < total_inputs or gate.rightParentID < total_inputs


def regenerate_gates(circuit: TransformedCircuit, is_obfuscated: List[bool]) -> None:
    """
    Regenerate truth tables for obfuscated gates
    
    Strategy:
    - Level-1 gates (connected to inputs): Randomize to look like XOR (balanced)
    - Higher-level gates: Randomize to any non-constant gate
    
    Args:
        circuit: Transformed circuit (gates modified in place)
        is_obfuscated: Obfuscated wire tracking array
    """
    for gate in circuit.gates:
        if is_obfuscated[gate.outputID]:
            if is_level_1_gate(circuit, gate):
                # Level-1 gate: must look like XOR to prevent detection
                # XOR-like: balanced with 2 ones and 2 zeros
                rand_bit = generate_random_bool()
                gate.truthTable[0][0] = rand_bit
                gate.truthTable[0][1] = not rand_bit
                gate.truthTable[1][0] = not rand_bit
                gate.truthTable[1][1] = rand_bit
            else:
                # Higher-level gate: randomize to non-constant gate
                # Avoid 0000 (always false) and 1111 (always true)
                while True:
                    tt = [
                        [generate_random_bool(), generate_random_bool()],
                        [generate_random_bool(), generate_random_bool()]
                    ]
                    
                    # Check has at least one True and one False
                    flat = [tt[0][0], tt[0][1], tt[1][0], tt[1][1]]
                    if True in flat and False in flat:
                        gate.truthTable = tt
                        break
