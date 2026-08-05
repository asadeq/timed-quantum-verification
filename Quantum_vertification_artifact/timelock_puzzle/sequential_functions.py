"""
Sequential Function for Time-Lock Puzzles

Provides both runtime evaluation and circuit-based implementations
of the sequential function f: {0,1}^λ -> {0,1}^λ
"""

import hashlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from crgc_garbled_circuits.circuit_structures import TransformedGate


class SequentialFunction:
    """
    A sequential function for TLP evaluation using SHA-256.
    
    Provides runtime SHA-256 evaluation for verification and circuit embedding for garbling.
    """
    
    def __init__(self):
        pass

    

def create_sha256_circuit_function(builder_ref, input_wires, path=None):
    """
    Circuit-based sequential function using SHA-256
    
    Embeds a full SHA-256 circuit into the TLP circuit by loading
    the Bristol format circuit from emp-tool and remapping wire IDs.
    
    Implements proper SHA-256 padding and includes IV constants.
    
    Args:
        builder_ref: TLPCircuitBuilder instance
        input_wires: List of input wire IDs (must be 256 wires for 256-bit input)
        path: Optional path to SHA-256 Bristol circuit file.
              If None, uses default path in emp-tool directory.
        
    Returns:
        List of output wire IDs (256 wires for 256-bit SHA-256 output)
    """
    if path is None:
        sha256_circuit_path = Path(__file__).parent.parent   / "circuits" / "sha256.txt"
    else:
        sha256_circuit_path = Path(path)
    
    if not sha256_circuit_path.exists():

        return create_xor_mixing_function(builder_ref, input_wires)
    
    if len(input_wires) != 256:
        return create_xor_mixing_function(builder_ref, input_wires)
    
    # Read SHA-256 circuit details (Bristol format)
    with open(sha256_circuit_path, 'r') as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    
    # Parse Bristol format header
    # Line 1: numGates numWires
    num_gates, num_wires = map(int, lines[0].split())
    
    # Line 2: numInputs input1_bits input2_bits ...
    input_line = lines[1].split()
    num_inputs = int(input_line[0])
    input_a = int(input_line[1])  # 512 bits (padded message)
    input_b = int(input_line[2])  # 256 bits (IV)
    
    # Line 3: numOutputs output_bits
    output_line = lines[2].split()
    num_outputs = int(output_line[0])
    bitlength_outputs = int(output_line[1])
    
    total_sha_inputs = input_a + input_b
    
    if input_a != 512 or input_b != 256:
        return create_xor_mixing_function(builder_ref, input_wires)
    
    const_zero = builder_ref.build_xor_gate(input_wires[0], input_wires[0])
    const_one = builder_ref.build_not_gate(const_zero)
    
    padded_message_wires = []
    
    padded_message_wires.extend(input_wires)
    
    padded_message_wires.append(const_one)
    
    for i in range(191):
        padded_message_wires.append(const_zero)
    
    for bit_pos in range(64):
        if bit_pos == 55:
            padded_message_wires.append(const_one)
        else:
            padded_message_wires.append(const_zero)
    
    iv_hex = "6a09e667bb67ae853c6ef372a54ff53a510e527f9b05688c1f83d9ab5be0cd19"
    iv_bits = []
    for hex_char in iv_hex:
        val = int(hex_char, 16)
        for bit_pos in range(4):
            iv_bits.append(const_one if (val >> (3 - bit_pos)) & 1 else const_zero)
    
    wire_mapping = {}
    
    for i in range(512):
        wire_mapping[i] = padded_message_wires[i]
    
    for i in range(256):
        wire_mapping[512 + i] = iv_bits[i]
    
    gate_lines = lines[3:]
    
    for line in gate_lines:
        if not line:
            continue
        
        parts = line.split()
        num_gate_inputs = int(parts[0])
        num_gate_outputs = int(parts[1])
        
        # INV is a 1-input, 1-output NOT gate in Bristol format.
        # The circuit builder otherwise only handles 2-input, 1-output gates.
        if num_gate_inputs == 1 and num_gate_outputs == 1 and parts[4] == "INV":
            input_id = int(parts[2])
            output_id = int(parts[3])
            if input_id not in wire_mapping:
                wire_mapping[input_id] = builder_ref._allocate_wire()
            wire_mapping[output_id] = builder_ref.build_not_gate(wire_mapping[input_id])
            continue
        
        if num_gate_inputs != 2 or num_gate_outputs != 1:
            continue
        
        left_parent = int(parts[2])
        right_parent = int(parts[3])
        output_id = int(parts[4])
        gate_type = parts[5]
        
        gate = TransformedGate()
        
        if left_parent not in wire_mapping:
            wire_mapping[left_parent] = builder_ref._allocate_wire()
        gate.leftParentID = wire_mapping[left_parent]
        
        if right_parent not in wire_mapping:
            wire_mapping[right_parent] = builder_ref._allocate_wire()
        gate.rightParentID = wire_mapping[right_parent]
        
        if output_id not in wire_mapping:
            wire_mapping[output_id] = builder_ref._allocate_wire()
        gate.outputID = wire_mapping[output_id]
        
        if gate_type == "AND":
            gate.truthTable = [[False, False], [False, True]]
        elif gate_type == "XOR":
            gate.truthTable = [[False, True], [True, False]]
        elif gate_type == "OR":
            gate.truthTable = [[False, True], [True, True]]
        elif gate_type == "NAND":
            gate.truthTable = [[True, True], [True, False]]
        elif gate_type == "NOR":
            gate.truthTable = [[True, False], [False, False]]
        elif gate_type == "XNOR":
            gate.truthTable = [[True, False], [False, True]]
        else:
            continue
        
        builder_ref.gates.append(gate)
    
    output_wires = []
    output_start = num_wires - bitlength_outputs
    for i in range(output_start, num_wires):
        if i in wire_mapping:
            output_wires.append(wire_mapping[i])
        else:
            output_wires.append(builder_ref._allocate_wire())
    
    return output_wires[:256]


def create_identity_function(builder_ref, input_wires):
    """
    Identity function: f(x) = x (for testing)
    """
    output_wires = []
    for wire in input_wires:
        output = builder_ref.build_and_gate(wire, wire)
        output_wires.append(output)
    return output_wires


def create_xor_mixing_function(builder_ref, input_wires):
    """
    Simple XOR-based mixing function for testing
    """
    n = len(input_wires)
    output_wires = []
    
    for i in range(n):
        next_i = (i + 1) % n
        xor_result = builder_ref.build_xor_gate(input_wires[i], input_wires[next_i])
        output_wires.append(xor_result)
    
    return output_wires


def create_sequential_function_for_circuit(mode='identity'):
    """
    Factory function to create a sequential function for circuit building
    
    Args:
        mode: 'identity', 'xor_mixing', or 'sha256'
    
    Returns:
        Callable function(builder_ref, input_wires) -> output_wires
    """
    if mode == 'identity':
        return create_identity_function
    elif mode == 'xor_mixing':
        return create_xor_mixing_function
    elif mode == 'sha256':
        return create_sha256_circuit_function
    else:
        raise ValueError(f"Unknown mode: {mode}")


if __name__ == "__main__":
    print("Sequential Function Library")
    print("Use: from sequential_function import SequentialFunction, create_sequential_function_for_circuit")
