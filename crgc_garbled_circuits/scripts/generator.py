#!/usr/bin/env python3
"""
CRGC Generator
Transforms Bristol Fashion circuits into Completely Reusable Garbled Circuits
"""

import argparse
import time
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from .. import *


def main():
    parser = argparse.ArgumentParser(description='CRGC Generator - Transform circuits to reusable garbled circuits')
    parser.add_argument('--circuit', default='adder64', help='Circuit name (default: adder64)')
    parser.add_argument('--type', default='txt', choices=['txt', 'python'], help='Circuit type: txt (Bristol file) or python (Python function) (default: txt)')
    parser.add_argument('--format', default='bristol', choices=['bristol', 'emp'], 
                       help='Circuit format (default: bristol)')
    parser.add_argument('--inputa', default='r', 
                       help='Input A: "r" for random, integer, or filename (default: r)')
    parser.add_argument('--inputb', default='r', 
                       help='Input B: "r" for random, integer, or filename (default: r)')
    parser.add_argument('--store', default='txt', choices=['txt', 'off'], 
                       help='Storage format (default: txt)')
    parser.add_argument('--threads', type=int, default=1, 
                       help='Number of threads (not implemented, reserved for future)')
    parser.add_argument('--use-numpy', action='store_true', 
                       help='Use numpy acceleration (if available)')
    parser.add_argument('--input-bits-a', type=int, default=64,
                       help='Bit width for input A when using Python functions (default: 64)')
    parser.add_argument('--input-bits-b', type=int, default=64,
                       help='Bit width for input B when using Python functions (default: 64)')
    parser.add_argument('--output-bits', type=int, default=64,
                       help='Bit width for output when using Python functions (default: 64)')
    parser.add_argument('--export-bristol', action='store_true',
                       help='Export Python function to Bristol format file')
    
    args = parser.parse_args()
    
    # Step 1: Load or compile circuit
    t1 = time.time()
    
    if args.type == 'python':
        # Import Python function and compile to circuit
        from crgc import PythonCircuitCompiler, export_to_bristol
        
        # Import the Python module containing the circuit function
        circuit_module_path = Path(__file__).parent / 'circuits' / f"{args.circuit}.py"
        if not circuit_module_path.exists():
            print(f"Error: Python circuit file not found: {circuit_module_path}")
            return 1
        
        # Load the module dynamically
        import importlib.util
        spec = importlib.util.spec_from_file_location(args.circuit, circuit_module_path)
        circuit_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(circuit_module)
        
        # Get the circuit function (should be named 'circuit' or same as module name)
        if hasattr(circuit_module, 'circuit'):
            circuit_func = circuit_module.circuit
        elif hasattr(circuit_module, args.circuit):
            circuit_func = getattr(circuit_module, args.circuit)
        else:
            print(f"Error: No 'circuit' function found in {args.circuit}.py")
            return 1
        
        # Compile to circuit
        compiler = PythonCircuitCompiler()
        circuit = compiler.compile(
            circuit_func,
            args.input_bits_a,
            args.input_bits_b,
            args.output_bits
        )
        
        # Optionally export to Bristol format
        if args.export_bristol:
            bristol_path = Path(__file__).parent.parent / 'src' / 'circuits' / f"{args.circuit}_python.txt"
            export_to_bristol(circuit, str(bristol_path))
            print(f"---INFO--- Exported to Bristol format: {bristol_path}")
        
        elapsed_ms = int((time.time() - t1) * 1000)
        print(f"---TIMING--- {elapsed_ms}ms compiling Python function to circuit")
        print(f"---INFO--- numGates: {circuit.details.numGates}")
    
    else:
        # Load Bristol circuit from file
        # Check if it's an absolute path or just a circuit name
        if Path(args.circuit).is_absolute() or '/' in args.circuit:
            circuit_path = Path(args.circuit)
        else:
            circuit_path = Path(__file__).parent.parent / 'src' / 'circuits' / f"{args.circuit}.txt"
        
        if not circuit_path.exists():
            print(f"Error: Circuit file not found: {circuit_path}")
            return 1
        
        details = import_bristol_circuit_details(str(circuit_path), args.format)
        circuit = import_bristol_circuit_ex_not(str(circuit_path), details)
        elapsed_ms = int((time.time() - t1) * 1000)
        print(f"---TIMING--- {elapsed_ms}ms converting program to circuit")
        print(f"---INFO--- numGates: {circuit.details.numGates}")
    
    # Step 2: Predict leakage (diagnostics)
    t1 = time.time()
    parents = get_parents_of_each_wire(circuit)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms getting Parents of each Wire")
    
    po = [False] * circuit.details.numWires
    
    t1 = time.time()
    get_potentially_obfuscated_fixed_gates(circuit, po)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms identifying potentially obfuscated fixed gates")
    
    t1 = time.time()
    get_potentially_intermediary_gates_from_output(circuit.details, po, parents)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms identifying potentially intermediary gates")
    
    # Count potentially obfuscated gates (excluding input wires)
    poc = sum(po) - circuit.details.bitlengthInputA
    print(f"---INFO--- potentially obfuscated fixed and intermediary gates: {poc}")
    
    t1 = time.time()
    leaked = get_leaked_inputs(circuit, po)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms predict leaked inputs")
    leaked_str = ' '.join(map(str, leaked)) if leaked else ''
    print(f"---INFO--- {len(leaked)} leaked inputs: {leaked_str}")
    
    # Step 3: Parse inputs
    try:
        inputA = parse_input(args.inputa, circuit.details.bitlengthInputA, args.circuit, 'A')
        inputB = parse_input(args.inputb, circuit.details.bitlengthInputB, args.circuit, 'B')
    except Exception as e:
        print(f"Error parsing inputs: {e}")
        return 1
    
    # Step 4: Evaluate original circuit
    t1 = time.time()
    if args.use_numpy and args.format == 'emp':
        original_output = evaluate_sorted_transformed_circuit(circuit, inputA, inputB)
    elif args.format == 'emp':
        original_output = evaluate_sorted_transformed_circuit(circuit, inputA, inputB)
    else:
        original_output = evaluate_transformed_circuit(circuit, inputA, inputB)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms evaluate circuit")
    
    inA_int = bool_array_to_int(inputA)
    inB_int = bool_array_to_int(inputB)
    out_int = bool_array_to_int(original_output)
    print(f"---Evaluation--- inA{inA_int}")
    print(f"---Evaluation--- inB{inB_int}")
    print(f"---Evaluation--- out{out_int}")
    
    # Step 5: Obfuscate input and flip circuit
    obfuscated_val_arr, flipped = obfuscate_input(inputA, circuit.details.numWires)
    
    t1 = time.time()
    get_flipped_circuit(circuit, flipped)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms flip circuit")
    
    # Step 6: Identify fixed gates
    t1 = time.time()
    is_obfuscated = identify_fixed_gates_arr(circuit, obfuscated_val_arr)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms identify fixed Gates")
    
    obf_count = sum(is_obfuscated)
    print(f"---INFO--- obfuscated gates: {obf_count}")
    
    # Step 7: Identify intermediary gates
    t1 = time.time()
    get_intermediary_gates_from_output(circuit.details, is_obfuscated, parents)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms identify intermediary gates")
    
    final_obf = sum(is_obfuscated) - circuit.details.bitlengthInputA
    print(f"---INFO--- obfuscated fixed and intermediary gates: {final_obf}")
    
    # Step 8: Regenerate obfuscated gates
    t1 = time.time()
    regenerate_gates(circuit, is_obfuscated)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms obfuscate gates")
    
    # Step 9: Verify integrity
    if args.format == 'emp':
        rgc_output = evaluate_sorted_transformed_circuit(circuit, obfuscated_val_arr, inputB)
    else:
        rgc_output = evaluate_transformed_circuit(circuit, obfuscated_val_arr, inputB)
    
    if rgc_output == original_output:
        print("---Success--- Evaluation of original circuit and constructed RGC are equal")
    else:
        print("---Error--- RGC output does not match original!")
        return 1
    
    obf_inA_int = bool_array_to_int(obfuscated_val_arr)
    rgc_out_int = bool_array_to_int(rgc_output)
    print(f"---Evaluation--- inA{obf_inA_int}")
    print(f"---Evaluation--- inB{inB_int}")
    print(f"---Evaluation--- out{rgc_out_int}")
    
    # Step 10: Export RGC
    if args.store == 'txt':
        t1 = time.time()
        output_path = Path(__file__).parent / 'circuits' / args.circuit
        export_circuit_separate_files(circuit, output_path)
        export_obfuscated_input(obfuscated_val_arr, circuit.details, output_path)
        elapsed_ms = int((time.time() - t1) * 1000)
        print(f"---TIMING--- {elapsed_ms}ms exporting")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
