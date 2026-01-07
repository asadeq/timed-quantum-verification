"""
Fixed gate identification for CRGC
Identifies gates that can be determined from obfuscated input
"""

from typing import List
from .circuit_structures import TransformedCircuit


def identify_fixed_gates_arr(circuit: TransformedCircuit, obfuscated_val_arr: List[bool]) -> List[bool]:
    """
    Identify which gates are "fixed" (determinable from obfuscated input)
    
    A gate is fixed if:
    - Both parents are obfuscated (known values)
    - One parent is obfuscated and gate output is independent of other parent
    
    Also recovers gate integrity by copying known columns/rows to unknown.
    
    Args:
        circuit: Transformed circuit (gates modified in place for integrity)
        obfuscated_val_arr: Obfuscated generator input
    
    Returns:
        Boolean array marking obfuscated (fixed) wires
    """
    is_obfuscated = [False] * circuit.details.numWires
    unobfuscated_values = [False] * circuit.details.numWires
    
    # Mark InputA wires as obfuscated with their values
    for i in range(circuit.details.bitlengthInputA):
        unobfuscated_values[i] = obfuscated_val_arr[circuit.details.bitlengthInputA - 1 - i]
        is_obfuscated[i] = True
    
    # InputB wires are NOT obfuscated
    
    # Output wire range (cannot mark these as obfuscated)
    output_start = circuit.details.numWires - circuit.details.numOutputs * circuit.details.bitlengthOutputs
    
    for gate in circuit.gates:
        left_parent = gate.leftParentID
        right_parent = gate.rightParentID
        output_id = gate.outputID
        
        if is_obfuscated[left_parent] and is_obfuscated[right_parent]:
            # Both parents obfuscated - can determine output
            if output_id < output_start:
                left_val = int(unobfuscated_values[left_parent])
                right_val = int(unobfuscated_values[right_parent])
                unobfuscated_values[output_id] = gate.truthTable[left_val][right_val]
                is_obfuscated[output_id] = True
        
        elif is_obfuscated[left_parent]:
            # Left parent obfuscated, check if output is fixed
            left_val = int(unobfuscated_values[left_parent])
            
            if gate.truthTable[left_val][0] == gate.truthTable[left_val][1]:
                # Output is independent of right parent
                if output_id < output_start:
                    unobfuscated_values[output_id] = gate.truthTable[left_val][0]
                    is_obfuscated[output_id] = True
            else:
                # Recover integrity: copy known column to unknown
                gate.truthTable[int(not left_val)][0] = gate.truthTable[left_val][0]
                gate.truthTable[int(not left_val)][1] = gate.truthTable[left_val][1]
        
        elif is_obfuscated[right_parent]:
            # Right parent obfuscated, check if output is fixed
            right_val = int(unobfuscated_values[right_parent])
            
            if gate.truthTable[0][right_val] == gate.truthTable[1][right_val]:
                # Output is independent of left parent
                if output_id < output_start:
                    unobfuscated_values[output_id] = gate.truthTable[0][right_val]
                    is_obfuscated[output_id] = True
            else:
                # Recover integrity: copy known row to unknown
                gate.truthTable[0][int(not right_val)] = gate.truthTable[0][right_val]
                gate.truthTable[1][int(not right_val)] = gate.truthTable[1][right_val]
    
    return is_obfuscated
