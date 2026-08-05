"""
Bristol Fashion format exporter for circuits
Exports circuits in the standard Bristol format with headers and gate labels
"""

from pathlib import Path
from .circuit_structures import TransformedCircuit


def export_bristol_format(circuit: TransformedCircuit, output_path: Path) -> None:
    """
    Export circuit in Bristol Fashion format
    
    Bristol format:
    Line 1: num_gates num_wires
    Line 2: num_inputs input_bit_lengths...
    Line 3: num_outputs output_bit_lengths...
    Gates: num_inputs num_outputs input_wires... output_wire gate_type
    
    Args:
        circuit: Circuit to export
        output_path: Output file path
    """
    output_path = Path(output_path)
    
    # Truth table to gate type mapping
    def truth_table_to_gate_type(tt):
        """Convert truth table to gate name"""
        tt_str = f"{int(tt[0][0])}{int(tt[0][1])}{int(tt[1][0])}{int(tt[1][1])}"
        
        gate_map = {
            '0001': 'AND',
            '0111': 'OR',
            '0110': 'XOR',
            '1000': 'NOR',
            '1001': 'XNOR',
            '1110': 'NAND',
            '1011': 'INV_A',  # NOT left (left implies right)
            '1101': 'INV_B',  # NOT right (right implies left)
            '0000': 'FALSE',
            '1111': 'TRUE',
            '0010': 'A_AND_NOT_B',
            '0100': 'NOT_A_AND_B',
            '1010': 'NOT_A',
            '0101': 'NOT_B',
            '0011': 'A',
            '1100': 'B',
        }
        
        return gate_map.get(tt_str, f'GATE_{tt_str}')
    
    with open(output_path, 'w') as f:
        # Header line 1: num_gates num_wires
        f.write(f"{circuit.details.numGates} {circuit.details.numWires}\n")
        
        # Header line 2: num_inputs input_bit_lengths...
        f.write(f"2 {circuit.details.bitlengthInputA} {circuit.details.bitlengthInputB}\n")
        
        # Header line 3: num_outputs output_bit_lengths...
        f.write(f"{circuit.details.numOutputs} {circuit.details.bitlengthOutputs}\n")
        
        # Empty line (optional, for readability)
        f.write("\n")
        
        # Gates: 2 1 left_wire right_wire output_wire gate_type
        for gate in circuit.gates:
            gate_type = truth_table_to_gate_type(gate.truthTable)
            f.write(f"2 1 {gate.leftParentID} {gate.rightParentID} {gate.outputID} {gate_type}\n")


def export_bristol_and_rgc(circuit: TransformedCircuit, base_path: Path) -> None:
    """
    Export circuit in both Bristol and RGC formats
    
    Args:
        circuit: Circuit to export
        base_path: Base path (without extension)
    """
    from .circuit_writer import export_circuit_separate_files
    
    base_path = Path(base_path)
    
    # Export RGC format (separate files)
    export_circuit_separate_files(circuit, base_path)
    
    # Export Bristol format (single file)
    bristol_path = base_path.parent / f"{base_path.name}_bristol.txt"
    export_bristol_format(circuit, bristol_path)
    
    print(f"RGC format: {base_path}_rgc.txt + {base_path}_rgc_details.txt")
    print(f"Bristol format: {bristol_path}")
