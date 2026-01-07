"""
Circuit writer for RGC format export
Writes transformed circuits to RGC format files
"""

from pathlib import Path
from typing import List
from .circuit_structures import TransformedCircuit, CircuitDetails


def export_circuit_separate_files(circuit: TransformedCircuit, destination_path: Path) -> None:
    """
    Export circuit to separate RGC format files
    
    Creates:
    - <name>_rgc_details.txt: Circuit metadata
    - <name>_rgc.txt: Gate list with truth tables
    
    Args:
        circuit: Transformed circuit to export
        destination_path: Base path for output files (without extension)
    """
    destination_path = Path(destination_path)
    
    # Write _rgc_details.txt
    details_path = destination_path.parent / f"{destination_path.name}_rgc_details.txt"
    with open(details_path, 'w') as f:
        f.write(f"{circuit.details.numGates} {circuit.details.numWires}\n")
        f.write(f"{circuit.details.bitlengthInputA} {circuit.details.bitlengthInputB}\n")
        f.write(f"{circuit.details.numOutputs} {circuit.details.bitlengthOutputs}\n")
    
    # Write _rgc.txt
    circuit_path = destination_path.parent / f"{destination_path.name}_rgc.txt"
    with open(circuit_path, 'w') as f:
        for gate in circuit.gates:
            tt = gate.truthTable
            tt_str = f"{int(tt[0][0])}{int(tt[0][1])}{int(tt[1][0])}{int(tt[1][1])}"
            f.write(f"{gate.leftParentID} {gate.rightParentID} {gate.outputID} {tt_str}\n")


def export_obfuscated_input(obfuscated_val_arr: List[bool], details: CircuitDetails, destination_path: Path) -> None:
    """
    Export obfuscated input to RGC format file
    
    Creates:
    - <name>_rgc_inputA.txt: Binary string of obfuscated input
    
    Args:
        obfuscated_val_arr: Obfuscated generator input
        details: Circuit metadata
        destination_path: Base path for output file (without extension)
    """
    destination_path = Path(destination_path)
    
    # Write _rgc_inputA.txt
    input_path = destination_path.parent / f"{destination_path.name}_rgc_inputA.txt"
    with open(input_path, 'w') as f:
        binary_str = ''.join(['1' if b else '0' for b in obfuscated_val_arr])
        f.write(binary_str + '\n')
