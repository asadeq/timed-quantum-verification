"""
Bristol Fashion circuit reader and RGC importer
Handles parsing of Bristol circuits and RGC format files
"""

from pathlib import Path
from typing import List
from .circuit_structures import CircuitDetails, TransformedGate, TransformedCircuit
from .helper_functions import swap_left_parent, swap_right_parent, flip_table


def import_bristol_circuit_details(filepath: str, format: str = 'bristol') -> CircuitDetails:
    """
    Import circuit metadata from Bristol Fashion or RGC format file
    
    Args:
        filepath: Path to circuit details file
        format: 'bristol', 'emp', or 'rgc'
    
    Returns:
        CircuitDetails object
    """
    details = CircuitDetails()
    
    with open(filepath, 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    
    if format == 'bristol':
        # Line 1: numGates numWires
        parts = lines[0].split()
        details.numGates = int(parts[0])
        details.numWires = int(parts[1])
        
        # Line 2: numInputs bitlengthInputA bitlengthInputB ...
        parts = lines[1].split()
        details.bitlengthInputA = int(parts[1])
        details.bitlengthInputB = int(parts[2])
        
        # Line 3: numOutputs bitlengthOutputs
        parts = lines[2].split()
        details.numOutputs = int(parts[0])
        details.bitlengthOutputs = int(parts[1])
    
    elif format == 'emp':
        # Line 1: numGates numWires
        parts = lines[0].split()
        details.numGates = int(parts[0])
        details.numWires = int(parts[1])
        
        # Line 2: bitlengthInputA bitlengthInputB bitlengthOutputs
        parts = lines[1].split()
        details.bitlengthInputA = int(parts[0])
        details.bitlengthInputB = int(parts[1])
        details.bitlengthOutputs = int(parts[2])
        details.numOutputs = 1
    
    elif format == 'rgc':
        # Line 1: numGates numWires
        parts = lines[0].split()
        details.numGates = int(parts[0])
        details.numWires = int(parts[1])
        
        # Line 2: bitlengthInputA bitlengthInputB
        parts = lines[1].split()
        details.bitlengthInputA = int(parts[0])
        details.bitlengthInputB = int(parts[1])
        
        # Line 3: numOutputs bitlengthOutputs
        parts = lines[2].split()
        details.numOutputs = int(parts[0])
        details.bitlengthOutputs = int(parts[1])
    
    return details


def import_bristol_circuit_ex_not(filepath: str, details: CircuitDetails) -> TransformedCircuit:
    """
    Import Bristol circuit while eliminating NOT gates
    
    NOT gates are eliminated by tracking wire mappings and flips.
    Truth tables are swapped when consuming flipped wires.
    
    Args:
        filepath: Path to Bristol circuit file
        details: Circuit metadata
    
    Returns:
        TransformedCircuit with NOT gates eliminated
    """
    circuit = TransformedCircuit(details)
    
    # Track wire mappings and flips
    exchange_gate = list(range(details.numWires))
    flipped = [False] * details.numWires
    
    # Output wire range (cannot eliminate NOTs on these)
    output_start = details.numWires - details.numOutputs * details.bitlengthOutputs
    
    with open(filepath, 'r') as f:
        lines = f.readlines()[3:]  # Skip 3-line header
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        
        # Parse gate
        num_inputs = int(parts[0])
        num_outputs = int(parts[1])
        
        if num_inputs == 1 and num_outputs == 1:
            # NOT gate (INV)
            parent_id = int(parts[2])
            output_id = int(parts[3])
            
            # Check if output is a circuit output wire
            if output_id >= output_start:
                # Cannot eliminate NOT on output wire
                # Convert to XOR with same input twice, then flip
                gate = TransformedGate()
                gate.leftParentID = exchange_gate[parent_id]
                gate.rightParentID = exchange_gate[parent_id]
                gate.outputID = output_id
                gate.truthTable = [[False, False], [False, False]]  # Will be set below
                
                # XOR truth table: [[0,1],[1,0]]
                gate.truthTable[0][0] = False
                gate.truthTable[0][1] = True
                gate.truthTable[1][0] = True
                gate.truthTable[1][1] = False
                
                # Apply parent flip if needed
                if flipped[parent_id]:
                    swap_left_parent(gate.truthTable)
                
                # Flip output (NOT effect)
                flip_table(gate.truthTable)
                
                circuit.add_gate(gate)
            else:
                # Eliminate NOT gate via wire mapping
                exchange_gate[output_id] = exchange_gate[parent_id]
                flipped[output_id] = not flipped[parent_id]
        
        elif num_inputs == 2 and num_outputs == 1:
            # Two-input gate (XOR, AND, OR)
            left_parent = int(parts[2])
            right_parent = int(parts[3])
            output_id = int(parts[4])
            gate_type = parts[5]
            
            gate = TransformedGate()
            gate.leftParentID = exchange_gate[left_parent]
            gate.rightParentID = exchange_gate[right_parent]
            gate.outputID = output_id
            
            # Set truth table based on gate type
            if gate_type == 'XOR':
                gate.truthTable = [[False, True], [True, False]]
            elif gate_type == 'AND':
                gate.truthTable = [[False, False], [False, True]]
            elif gate_type == 'OR':
                gate.truthTable = [[False, True], [True, True]]
            else:
                raise ValueError(f"Unknown gate type: {gate_type}")
            
            # Apply flips from parent wires
            if flipped[left_parent]:
                swap_left_parent(gate.truthTable)
            if flipped[right_parent]:
                swap_right_parent(gate.truthTable)
            
            circuit.add_gate(gate)
    
    # Note: We don't adjust wire indices after NOT elimination
    # The C++ implementation keeps the same wire numbering
    # Update circuit details
    circuit.details.numGates = len(circuit.gates)
    
    return circuit


def import_transformed_circuit(filepath: str, details: CircuitDetails) -> TransformedCircuit:
    """
    Import RGC format circuit
    
    RGC format: leftID rightID outID tt00tt01tt10tt11
    
    Args:
        filepath: Path to RGC circuit file
        details: Circuit metadata
    
    Returns:
        TransformedCircuit
    """
    circuit = TransformedCircuit(details)
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) != 4:
                continue
            
            gate = TransformedGate()
            gate.leftParentID = int(parts[0])
            gate.rightParentID = int(parts[1])
            gate.outputID = int(parts[2])
            
            # Parse truth table from 4-character string
            tt_str = parts[3]
            if len(tt_str) != 4:
                raise ValueError(f"Invalid truth table string: {tt_str}")
            
            gate.truthTable[0][0] = tt_str[0] == '1'
            gate.truthTable[0][1] = tt_str[1] == '1'
            gate.truthTable[1][0] = tt_str[2] == '1'
            gate.truthTable[1][1] = tt_str[3] == '1'
            
            circuit.add_gate(gate)
    
    return circuit


def import_obfuscated_input(filepath: str, bitlength: int) -> List[bool]:
    """
    Import obfuscated input from RGC format file
    
    Args:
        filepath: Path to RGC input file
        bitlength: Expected bit length
    
    Returns:
        Boolean array of obfuscated input
    """
    with open(filepath, 'r') as f:
        binary_str = f.read().strip()
    
    if len(binary_str) != bitlength:
        raise ValueError(f"Input file has {len(binary_str)} bits, expected {bitlength}")
    
    return [c == '1' for c in binary_str]
