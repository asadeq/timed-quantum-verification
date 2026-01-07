"""
Python function to Bristol circuit converter
Converts Python functions to boolean circuits for CRGC transformation
"""

import ast
import inspect
from typing import Callable, List, Tuple, Dict
from .circuit_structures import CircuitDetails, TransformedGate, TransformedCircuit


class PythonCircuitCompiler:
    """
    Compiles Python functions to boolean circuits
    
    Supports basic arithmetic and boolean operations.
    Functions must use type hints to specify bit widths.
    """
    
    def __init__(self):
        self.gates = []
        self.wire_counter = 0
        self.variable_wires: Dict[str, List[int]] = {}
        self.input_a_bits = 0
        self.input_b_bits = 0
        self.output_bits = 0
    
    def compile(self, func: Callable, input_a_bits: int, input_b_bits: int, output_bits: int) -> TransformedCircuit:
        """
        Compile a Python function to a circuit
        
        Args:
            func: Python function to compile (must take two integer arguments)
            input_a_bits: Bit width of first input
            input_b_bits: Bit width of second input
            output_bits: Bit width of output
        
        Returns:
            TransformedCircuit
        
        Example:
            def add(a: int, b: int) -> int:
                return a + b
            
            circuit = compiler.compile(add, 64, 64, 64)
        """
        self.input_a_bits = input_a_bits
        self.input_b_bits = input_b_bits
        self.output_bits = output_bits
        self.gates = []
        self.wire_counter = input_a_bits + input_b_bits
        self.variable_wires = {}
        
        # Allocate input wires
        self.variable_wires['a'] = list(range(input_a_bits))
        self.variable_wires['b'] = list(range(input_a_bits, input_a_bits + input_b_bits))
        
        # Parse function
        source = inspect.getsource(func)
        tree = ast.parse(source)
        
        # Find the function definition
        func_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_def = node
                break
        
        if not func_def:
            raise ValueError("Could not find function definition")
        
        # Compile function body
        result_wires = self._compile_function_body(func_def)
        
        # Ensure we have the right number of output bits
        if len(result_wires) < output_bits:
            # Pad with zeros (high bits)
            for _ in range(output_bits - len(result_wires)):
                zero_wire = self._allocate_wire()
                gate = TransformedGate()
                gate.leftParentID = 0
                gate.rightParentID = 0
                gate.outputID = zero_wire
                gate.truthTable = [[False, False], [False, False]]  # AND(0, 0) = 0
                self.gates.append(gate)
                result_wires.append(zero_wire)
        elif len(result_wires) > output_bits:
            result_wires = result_wires[:output_bits]
        
        # Map result wires to output positions (last N wires of circuit)
        # Bristol format expects: last numOutputs * bitlengthOutputs wires are outputs
        # Specifically: wire[numWires-1], wire[numWires-2], ..., wire[numWires-bitlengthOutputs]
        final_output_wires = []
        for i in range(output_bits):
            output_wire = self._allocate_wire()
            # Create buffer gate: AND(a, a) = a (identity)
            gate = TransformedGate()
            gate.leftParentID = result_wires[i]
            gate.rightParentID = result_wires[i]
            gate.outputID = output_wire
            gate.truthTable = [[False, False], [False, True]]  # AND
            self.gates.append(gate)
            final_output_wires.append(output_wire)
        
        # Verify output wires are at the correct positions
        # Expected: last output_bits wires (numWires-output_bits through numWires-1)
        expected_start = self.wire_counter - output_bits
        if final_output_wires[0] != expected_start:
            raise RuntimeError(
                f"Output wire positioning error: expected outputs at wires {expected_start}-{self.wire_counter-1}, "
                f"but got {final_output_wires[0]}-{final_output_wires[-1]}"
            )
        
        # Create circuit
        details = CircuitDetails()
        details.numGates = len(self.gates)
        details.numWires = self.wire_counter
        details.bitlengthInputA = input_a_bits
        details.bitlengthInputB = input_b_bits
        details.numOutputs = 1
        details.bitlengthOutputs = output_bits
        
        circuit = TransformedCircuit(details)
        circuit.gates = self.gates
        
        return circuit
    
    def _compile_function_body(self, func_def: ast.FunctionDef) -> List[int]:
        """Compile the function body and return output wires"""
        result_wires = None
        
        for stmt in func_def.body:
            if isinstance(stmt, ast.Return):
                result_wires = self._compile_expression(stmt.value)
                break
        
        if result_wires is None:
            raise ValueError("Function must have a return statement")
        
        # Ensure output wires are at the end of the wire sequence
        # The last output_bits wires should be the circuit outputs
        # We need to ensure they're properly positioned
        return result_wires
    
    def _compile_expression(self, expr: ast.expr) -> List[int]:
        """Compile an expression and return the output wires"""
        if isinstance(expr, ast.Name):
            # Variable reference
            if expr.id in self.variable_wires:
                return self.variable_wires[expr.id]
            raise ValueError(f"Unknown variable: {expr.id}")
        
        elif isinstance(expr, ast.BinOp):
            left_wires = self._compile_expression(expr.left)
            right_wires = self._compile_expression(expr.right)
            
            if isinstance(expr.op, ast.Add):
                return self._compile_addition(left_wires, right_wires)
            elif isinstance(expr.op, ast.Sub):
                return self._compile_subtraction(left_wires, right_wires)
            elif isinstance(expr.op, ast.BitXor):
                return self._compile_xor(left_wires, right_wires)
            elif isinstance(expr.op, ast.BitAnd):
                return self._compile_and(left_wires, right_wires)
            elif isinstance(expr.op, ast.BitOr):
                return self._compile_or(left_wires, right_wires)
            else:
                raise ValueError(f"Unsupported binary operation: {type(expr.op)}")
        
        elif isinstance(expr, ast.Constant):
            # Constant value
            value = expr.value
            if isinstance(value, int):
                return self._compile_constant(value, max(self.input_a_bits, self.input_b_bits))
            raise ValueError(f"Unsupported constant type: {type(value)}")
        
        else:
            raise ValueError(f"Unsupported expression type: {type(expr)}")
    
    def _compile_constant(self, value: int, bitwidth: int) -> List[int]:
        """Create wires for a constant value"""
        # Constants are represented as a series of wires with fixed values
        # For simplicity, we'll create them using XOR gates with inputs
        wires = []
        for i in range(bitwidth):
            bit = (value >> i) & 1
            wire = self._allocate_wire()
            
            # Create a gate that produces the constant bit
            # XOR(a, a) = 0, so we can use that
            if bit == 0:
                # XOR with itself = 0
                gate = TransformedGate()
                gate.leftParentID = 0  # Use first input wire
                gate.rightParentID = 0
                gate.outputID = wire
                gate.truthTable = [[False, True], [True, False]]  # XOR
                self.gates.append(gate)
            else:
                # NOT(XOR(a, a)) = 1, but we'll use OR(a, NOT(a))
                # For simplicity, use constant 1 by NOT(0)
                gate = TransformedGate()
                gate.leftParentID = 0
                gate.rightParentID = 0
                gate.outputID = wire
                gate.truthTable = [[True, False], [False, True]]  # XNOR
                self.gates.append(gate)
            
            wires.append(wire)
        
        return wires
    
    def _compile_xor(self, left_wires: List[int], right_wires: List[int]) -> List[int]:
        """Compile XOR operation"""
        result_wires = []
        for i in range(min(len(left_wires), len(right_wires))):
            wire = self._allocate_wire()
            gate = TransformedGate()
            gate.leftParentID = left_wires[i]
            gate.rightParentID = right_wires[i]
            gate.outputID = wire
            gate.truthTable = [[False, True], [True, False]]  # XOR
            self.gates.append(gate)
            result_wires.append(wire)
        
        return result_wires
    
    def _compile_and(self, left_wires: List[int], right_wires: List[int]) -> List[int]:
        """Compile AND operation"""
        result_wires = []
        for i in range(min(len(left_wires), len(right_wires))):
            wire = self._allocate_wire()
            gate = TransformedGate()
            gate.leftParentID = left_wires[i]
            gate.rightParentID = right_wires[i]
            gate.outputID = wire
            gate.truthTable = [[False, False], [False, True]]  # AND
            self.gates.append(gate)
            result_wires.append(wire)
        
        return result_wires
    
    def _compile_or(self, left_wires: List[int], right_wires: List[int]) -> List[int]:
        """Compile OR operation"""
        result_wires = []
        for i in range(min(len(left_wires), len(right_wires))):
            wire = self._allocate_wire()
            gate = TransformedGate()
            gate.leftParentID = left_wires[i]
            gate.rightParentID = right_wires[i]
            gate.outputID = wire
            gate.truthTable = [[False, True], [True, True]]  # OR
            self.gates.append(gate)
            result_wires.append(wire)
        
        return result_wires
    
    def _compile_addition(self, a_wires: List[int], b_wires: List[int]) -> List[int]:
        """Compile full adder circuit for addition"""
        n_bits = min(len(a_wires), len(b_wires))
        result_wires = []
        carry = None
        
        for i in range(n_bits):
            if carry is None:
                # First bit: half adder
                sum_wire, carry = self._half_adder(a_wires[i], b_wires[i])
            else:
                # Subsequent bits: full adder
                sum_wire, carry = self._full_adder(a_wires[i], b_wires[i], carry)
            
            result_wires.append(sum_wire)
        
        return result_wires
    
    def _compile_subtraction(self, a_wires: List[int], b_wires: List[int]) -> List[int]:
        """Compile subtractor circuit (a - b = a + (~b + 1))"""
        # Invert b using NAND(wire, wire) = NOT(wire)
        b_inv = []
        for wire in b_wires:
            inv_wire = self._allocate_wire()
            gate = TransformedGate()
            gate.leftParentID = wire
            gate.rightParentID = wire
            gate.outputID = inv_wire
            # NAND(a, a) = NOT(a)
            # NAND truth table: [[1,1], [1,0]]
            gate.truthTable = [[True, True], [True, False]]  # NAND
            self.gates.append(gate)
            b_inv.append(inv_wire)
        
        # Add 1 to inverted b, then add to a
        # This is a - b = a + ~b + 1
        n_bits = min(len(a_wires), len(b_inv))
        result_wires = []
        carry = True  # Start with carry = 1 for two's complement
        
        for i in range(n_bits):
            if i == 0:
                # First bit with initial carry of 1
                sum_wire, carry_wire = self._full_adder_with_const_carry(
                    a_wires[i], b_inv[i], True
                )
            else:
                sum_wire, carry_wire = self._full_adder(a_wires[i], b_inv[i], carry)
            
            result_wires.append(sum_wire)
            carry = carry_wire
        
        return result_wires
    
    def _half_adder(self, a: int, b: int) -> Tuple[int, int]:
        """Create half adder: sum = a XOR b, carry = a AND b"""
        # Sum
        sum_wire = self._allocate_wire()
        sum_gate = TransformedGate()
        sum_gate.leftParentID = a
        sum_gate.rightParentID = b
        sum_gate.outputID = sum_wire
        sum_gate.truthTable = [[False, True], [True, False]]  # XOR
        self.gates.append(sum_gate)
        
        # Carry
        carry_wire = self._allocate_wire()
        carry_gate = TransformedGate()
        carry_gate.leftParentID = a
        carry_gate.rightParentID = b
        carry_gate.outputID = carry_wire
        carry_gate.truthTable = [[False, False], [False, True]]  # AND
        self.gates.append(carry_gate)
        
        return sum_wire, carry_wire
    
    def _full_adder(self, a: int, b: int, cin: int) -> Tuple[int, int]:
        """Create full adder: sum = a XOR b XOR cin, cout = (a AND b) OR (cin AND (a XOR b))"""
        # First XOR: a XOR b
        xor1_wire = self._allocate_wire()
        xor1_gate = TransformedGate()
        xor1_gate.leftParentID = a
        xor1_gate.rightParentID = b
        xor1_gate.outputID = xor1_wire
        xor1_gate.truthTable = [[False, True], [True, False]]  # XOR
        self.gates.append(xor1_gate)
        
        # Sum: (a XOR b) XOR cin
        sum_wire = self._allocate_wire()
        sum_gate = TransformedGate()
        sum_gate.leftParentID = xor1_wire
        sum_gate.rightParentID = cin
        sum_gate.outputID = sum_wire
        sum_gate.truthTable = [[False, True], [True, False]]  # XOR
        self.gates.append(sum_gate)
        
        # Carry: (a AND b)
        and1_wire = self._allocate_wire()
        and1_gate = TransformedGate()
        and1_gate.leftParentID = a
        and1_gate.rightParentID = b
        and1_gate.outputID = and1_wire
        and1_gate.truthTable = [[False, False], [False, True]]  # AND
        self.gates.append(and1_gate)
        
        # Carry: cin AND (a XOR b)
        and2_wire = self._allocate_wire()
        and2_gate = TransformedGate()
        and2_gate.leftParentID = cin
        and2_gate.rightParentID = xor1_wire
        and2_gate.outputID = and2_wire
        and2_gate.truthTable = [[False, False], [False, True]]  # AND
        self.gates.append(and2_gate)
        
        # Carry out: (a AND b) OR (cin AND (a XOR b))
        cout_wire = self._allocate_wire()
        cout_gate = TransformedGate()
        cout_gate.leftParentID = and1_wire
        cout_gate.rightParentID = and2_wire
        cout_gate.outputID = cout_wire
        cout_gate.truthTable = [[False, True], [True, True]]  # OR
        self.gates.append(cout_gate)
        
        return sum_wire, cout_wire
    
    def _full_adder_with_const_carry(self, a: int, b: int, cin: bool) -> Tuple[int, int]:
        """Full adder with constant carry input"""
        if cin:
            # cin = 1: sum = NOT(a XOR b), carry = a OR b
            # Actually: sum = a XOR b XOR 1 = NOT(a XOR b)
            xor_wire = self._allocate_wire()
            xor_gate = TransformedGate()
            xor_gate.leftParentID = a
            xor_gate.rightParentID = b
            xor_gate.outputID = xor_wire
            xor_gate.truthTable = [[False, True], [True, False]]  # XOR
            self.gates.append(xor_gate)
            
            # Invert XOR result using NAND(wire, wire) = NOT(wire)
            sum_wire = self._allocate_wire()
            sum_gate = TransformedGate()
            sum_gate.leftParentID = xor_wire
            sum_gate.rightParentID = xor_wire
            sum_gate.outputID = sum_wire
            sum_gate.truthTable = [[True, True], [True, False]]  # NAND
            self.gates.append(sum_gate)
            
            # Carry: a OR b
            carry_wire = self._allocate_wire()
            carry_gate = TransformedGate()
            carry_gate.leftParentID = a
            carry_gate.rightParentID = b
            carry_gate.outputID = carry_wire
            carry_gate.truthTable = [[False, True], [True, True]]  # OR
            self.gates.append(carry_gate)
            
            return sum_wire, carry_wire
        else:
            # cin = 0: just use half adder
            return self._half_adder(a, b)
    
    def _allocate_wire(self) -> int:
        """Allocate a new wire"""
        wire = self.wire_counter
        self.wire_counter += 1
        return wire


def export_to_bristol(circuit: TransformedCircuit, filepath: str) -> None:
    """
    Export compiled circuit to Bristol Fashion format
    
    Args:
        circuit: Circuit to export
        filepath: Output file path
    """
    with open(filepath, 'w') as f:
        # Header line 1: numGates numWires
        f.write(f"{circuit.details.numGates} {circuit.details.numWires}\n")
        
        # Header line 2: numInputs bitlengthInputA bitlengthInputB
        f.write(f"2 {circuit.details.bitlengthInputA} {circuit.details.bitlengthInputB}\n")
        
        # Header line 3: numOutputs bitlengthOutputs
        f.write(f"{circuit.details.numOutputs} {circuit.details.bitlengthOutputs}\n")
        
        # Gates
        for gate in circuit.gates:
            # Convert truth table to gate type
            tt = gate.truthTable
            
            if tt == [[False, True], [True, False]]:
                gate_type = "XOR"
            elif tt == [[False, False], [False, True]]:
                gate_type = "AND"
            elif tt == [[False, True], [True, True]]:
                gate_type = "OR"
            else:
                # For other gates, default to XOR (will need manual adjustment)
                gate_type = "XOR"
            
            f.write(f"2 1 {gate.leftParentID} {gate.rightParentID} {gate.outputID} {gate_type}\n")
