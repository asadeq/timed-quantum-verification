"""
Leakage prediction and diagnostics for CRGC
Analyzes circuit structure to predict information leakage
"""

from typing import List, Tuple
from collections import deque
from .circuit_structures import TransformedCircuit, CircuitDetails


def get_parents_of_each_wire(circuit: TransformedCircuit) -> List[List[int]]:
    """
    Build parent tracking array for each wire
    
    Args:
        circuit: Transformed circuit
    
    Returns:
        List of [leftParent, rightParent] for each wire
    """
    parents = [[0, 0] for _ in range(circuit.details.numWires)]
    
    for gate in circuit.gates:
        parents[gate.outputID] = [gate.leftParentID, gate.rightParentID]
    
    return parents


def get_potentially_obfuscated_fixed_gates(circuit: TransformedCircuit, po: List[bool]) -> None:
    """
    Identify gates that are potentially obfuscated (determinable from InputA)
    
    A gate is potentially obfuscated if:
    - Both parents are potentially obfuscated, OR
    - One parent is potentially obfuscated and gate output is fixed
    
    Args:
        circuit: Transformed circuit
        po: Potentially obfuscated array (modified in place)
    """
    # Mark InputA wires as potentially obfuscated
    for i in range(circuit.details.bitlengthInputA):
        po[i] = True
    
    # Output wire range
    output_start = circuit.details.numWires - circuit.details.numOutputs * circuit.details.bitlengthOutputs
    
    # Track values for obfuscated wires
    values = [False] * circuit.details.numWires
    
    for gate in circuit.gates:
        left_parent = gate.leftParentID
        right_parent = gate.rightParentID
        output_id = gate.outputID
        
        if po[left_parent] and po[right_parent]:
            # Both parents obfuscated
            if output_id < output_start:
                po[output_id] = True
                values[output_id] = gate.truthTable[int(values[left_parent])][int(values[right_parent])]
        
        elif po[left_parent]:
            # Left parent obfuscated, check if output is fixed
            left_val = int(values[left_parent])
            if gate.truthTable[left_val][0] == gate.truthTable[left_val][1]:
                if output_id < output_start:
                    po[output_id] = True
                    values[output_id] = gate.truthTable[left_val][0]
        
        elif po[right_parent]:
            # Right parent obfuscated, check if output is fixed
            right_val = int(values[right_parent])
            if gate.truthTable[0][right_val] == gate.truthTable[1][right_val]:
                if output_id < output_start:
                    po[output_id] = True
                    values[output_id] = gate.truthTable[0][right_val]


def get_potentially_intermediary_gates_from_output(details: CircuitDetails, po: List[bool], parents: List[List[int]]) -> None:
    """
    Identify intermediary gates (gates on path from non-obfuscated to outputs)
    
    Uses backward BFS from output wires through parent graph.
    
    Args:
        details: Circuit metadata
        po: Potentially obfuscated array (modified in place)
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
                if not po[parent] and not added[parent]:
                    queue.append(parent)
                    added[parent] = True
    
    # Invert for gate wires (mark intermediary gates as obfuscated)
    output_start = details.numWires - details.numOutputs * details.bitlengthOutputs
    for wire in range(details.bitlengthInputA + details.bitlengthInputB, details.numWires):
        if wire < output_start:  # Not an output wire
            po[wire] = not not_obfuscated[wire]


def get_leaked_inputs(circuit: TransformedCircuit, po: List[bool]) -> List[int]:
    """
    Identify which InputA bits may be leaked
    
    An input bit is leaked if it's used by a non-obfuscated gate
    
    Args:
        circuit: Transformed circuit
        po: Potentially obfuscated array
    
    Returns:
        List of leaked input indices
    """
    leaked = []
    
    for gate in circuit.gates:
        if not po[gate.outputID]:
            # Gate is not obfuscated, check if it uses InputA
            if gate.leftParentID < circuit.details.bitlengthInputA:
                input_idx = circuit.details.bitlengthInputA - 1 - gate.leftParentID
                if input_idx not in leaked:
                    leaked.append(input_idx)
            
            if gate.rightParentID < circuit.details.bitlengthInputA:
                input_idx = circuit.details.bitlengthInputA - 1 - gate.rightParentID
                if input_idx not in leaked:
                    leaked.append(input_idx)
    
    return sorted(leaked)
