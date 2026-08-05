"""
TLP Circuit Builder

Builder for Time-Lock Puzzle circuits using CRGC.
Provides multiplexers and other conditional logic primitives.
"""

import sys
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from crgc_garbled_circuits import *
from typing import Callable, Callable, List


class TLPCircuitBuilder:
    """
    Builder for Time-Lock Puzzle circuits with conditional logic support
    """
    
    def __init__(self):
        self.gates = []
        self.wire_counter = 0
    
    def _allocate_wire(self) -> int:
        """Allocate a new wire ID"""
        wire = self.wire_counter
        self.wire_counter += 1
        return wire
    
    def build_not_gate(self, input_wire: int) -> int:
        """
        Build NOT gate: output = NOT(input)
        Implementation: NAND(a, a) = NOT(a)
        """
        output = self._allocate_wire()
        gate = TransformedGate()
        gate.leftParentID = input_wire
        gate.rightParentID = input_wire
        gate.outputID = output
        gate.truthTable = [[True, True], [True, False]]  # NAND
        self.gates.append(gate)
        return output
    
    def build_and_gate(self, left_wire: int, right_wire: int) -> int:
        """Build AND gate"""
        output = self._allocate_wire()
        gate = TransformedGate()
        gate.leftParentID = left_wire
        gate.rightParentID = right_wire
        gate.outputID = output
        gate.truthTable = [[False, False], [False, True]]  # AND
        self.gates.append(gate)
        return output
    
    def build_or_gate(self, left_wire: int, right_wire: int) -> int:
        """Build OR gate"""
        output = self._allocate_wire()
        gate = TransformedGate()
        gate.leftParentID = left_wire
        gate.rightParentID = right_wire
        gate.outputID = output
        gate.truthTable = [[False, True], [True, True]]  # OR
        self.gates.append(gate)
        return output
    
    def build_xor_gate(self, left_wire: int, right_wire: int) -> int:
        """Build XOR gate"""
        output = self._allocate_wire()
        gate = TransformedGate()
        gate.leftParentID = left_wire
        gate.rightParentID = right_wire
        gate.outputID = output
        gate.truthTable = [[False, True], [True, False]]  # XOR
        self.gates.append(gate)
        return output
    
    def build_mux_1bit(self, select: int, input0: int, input1: int) -> int:
        """
        Build 1-bit multiplexer
        
        MUX(select, input0, input1):
            - Returns input0 when select = 0
            - Returns input1 when select = 1
        
        Implementation: (~select & input0) | (select & input1)
        
        Args:
            select: Control bit wire
            input0: Wire to select when select=0
            input1: Wire to select when select=1
        
        Returns:
            Output wire
        """
        # NOT select
        not_select = self.build_not_gate(select)
        
        # ~select & input0
        and0 = self.build_and_gate(not_select, input0)
        
        # select & input1
        and1 = self.build_and_gate(select, input1)
        
        # and0 | and1
        result = self.build_or_gate(and0, and1)
        
        return result
    
    def build_mux_nbits(self, select: int, input0_wires: List[int], 
                        input1_wires: List[int]) -> List[int]:
        """
        Build n-bit multiplexer
        
        Applies MUX to each bit independently using the same select signal
        
        Args:
            select: Single control bit wire
            input0_wires: List of wires for first input (LSB first)
            input1_wires: List of wires for second input (LSB first)
        
        Returns:
            List of output wires (LSB first)
        """
        if len(input0_wires) != len(input1_wires):
            raise ValueError("Input wire lists must have same length")
        
        result_wires = []
        for i in range(len(input0_wires)):
            mux_out = self.build_mux_1bit(select, input0_wires[i], input1_wires[i])
            result_wires.append(mux_out)
        
        return result_wires
    
    def build_xor_nbits(self, wires_a: List[int], wires_b: List[int]) -> List[int]:
        """
        Build n-bit XOR
        
        XORs corresponding bits from two n-bit values
        
        Args:
            wires_a: First value wires (LSB first)
            wires_b: Second value wires (LSB first)
        
        Returns:
            Result wires (LSB first)
        """
        if len(wires_a) != len(wires_b):
            raise ValueError("Wire lists must have same length")
        
        result_wires = []
        for i in range(len(wires_a)):
            xor_out = self.build_xor_gate(wires_a[i], wires_b[i])
            result_wires.append(xor_out)
        
        return result_wires
    
    def build_tlp_output_circuit(self, b_wire: int, x_wires: List[int],
                                 m_wires: List[int], z_wires: List[int]) -> List[int]:
        """
        Build the TLP final output circuit
        
        Logic: If b == 0: return m, else return x XOR z
        
        Implementation: MUX(b, m, x^z)
        
        Args:
            b_wire: Selection bit (0=return m, 1=return x^z)
            x_wires: X value wires (LSB first)
            m_wires: M value wires (LSB first)
            z_wires: Z value wires (LSB first)
        
        Returns:
            Output wires (LSB first)
        """
        # Compute x XOR z
        xor_result = self.build_xor_nbits(x_wires, z_wires)
        
        # MUX(b, m, x^z)
        output_wires = self.build_mux_nbits(b_wire, m_wires, xor_result)
        
        return output_wires


def create_tlp_unrolled_circuit(T: int, sequential_func: Callable,
                                  message_bits: int = 256) -> TransformedCircuit:
    """
    Create a T-fold unrolled TLP circuit (C_T from the literature)
    
    This implements the full T-repetition circuit where:
    - Each iteration applies the sequential function f(x)
    - After T iterations, outputs based on b (m if b=0, x^z if b=1)
    
    Inputs:
        - b: 1 bit (selection bit)
        - x: message_bits (initial data)
        - m: message_bits (message)
        - z: message_bits (mask)
        - i: log2(T) bits (iteration counter - fixed to 1)
    
    Output:
        - message_bits: After T iterations of f, outputs m if b=0, else f^T(x)^z
    
    Args:
        T: Number of iterations to unroll
        message_bits: Number of bits for x, m, z (default: 256)
        sequential_func: Callable that implements f(x_wires) -> x_wires
                       
    
    Returns:
        TransformedCircuit with T repetitions

    """
    builder = TLPCircuitBuilder()
    
    # Calculate iteration counter bits
    import math
    i_bits = max(1, math.ceil(math.log2(T + 2))) if T > 0 else 1
    
    # Reserve input wires
    # Input A: b (1 bit) + x (message_bits) + i (i_bits)
    # Input B: m (message_bits) + z (message_bits)
    
    total_input_a = 1 + message_bits + i_bits
    total_input_b = 2 * message_bits
    
    builder.wire_counter = total_input_a + total_input_b
    
    # Wire assignments (accounting for evaluator reversal)
    # Logical InputA layout: [b (1 bit), x (message_bits), i (i_bits)]
    # After evaluator reversal:
    #   Wire 0 to i_bits-1: i counter (MSB to LSB after reversal)
    #   Wire i_bits to i_bits+message_bits-1: x (MSB to LSB after reversal)
    #   Wire total_input_a-1: b
    #
    # For InputB = [m (message_bits), z (message_bits)]:
    #   Wire total_input_a to total_input_a+message_bits-1: z (MSB to LSB)
    #   Wire total_input_a+message_bits to total_input_a+total_input_b-1: m (MSB to LSB)
    
    i_wires = list(range(0, i_bits))
    x_wires = list(range(i_bits, i_bits + message_bits))
    b_wire = total_input_a - 1
    z_wires = list(range(total_input_a, total_input_a + message_bits))
    m_wires = list(range(total_input_a + message_bits, total_input_a + total_input_b))
    

    
    # Unroll T iterations
    current_x = x_wires
    for iteration in range(T):
        current_x = sequential_func(builder, current_x)
    
    # After T iterations, apply final output logic:
    # output = MUX(b, m, current_x ^ z)
    output_wires = builder.build_tlp_output_circuit(b_wire, current_x, m_wires, z_wires)
    
    # Add buffer gates to position outputs correctly
    final_outputs = []
    for wire in output_wires:
        buf_wire = builder._allocate_wire()
        gate = TransformedGate()
        gate.leftParentID = wire
        gate.rightParentID = wire
        gate.outputID = buf_wire
        gate.truthTable = [[False, False], [False, True]]  # AND(a,a) = a (buffer)
        builder.gates.append(gate)
        final_outputs.append(buf_wire)
    
    # Create circuit
    details = CircuitDetails()
    details.numGates = len(builder.gates)
    details.numWires = builder.wire_counter
    details.bitlengthInputA = total_input_a
    details.bitlengthInputB = total_input_b
    details.numOutputs = 1
    details.bitlengthOutputs = message_bits
    
    circuit = TransformedCircuit(details)
    circuit.gates = builder.gates
    
    return circuit


if __name__ == "__main__":
    print("TLP Circuit Builder Library")
    print("Use: from tlp_circuit_builder import create_tlp_unrolled_circuit, TLPCircuitBuilder")
