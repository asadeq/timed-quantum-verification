#!/usr/bin/env python3
"""
CRGC Evaluator
Evaluates Completely Reusable Garbled Circuits
"""

import argparse
import time
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from .. import *


def main():
    parser = argparse.ArgumentParser(description='CRGC Evaluator - Evaluate reusable garbled circuits')
    parser.add_argument('--circuit', required=True, help='Circuit name')
    parser.add_argument('--inputb', default='r', 
                       help='Input B: "r" for random, integer, or filename (default: r)')
    parser.add_argument('--store', default='txt', choices=['txt'], 
                       help='Import format (default: txt)')
    parser.add_argument('--format', default='bristol', choices=['bristol', 'emp'], 
                       help='Circuit format (default: bristol)')
    parser.add_argument('--use-numpy', action='store_true', 
                       help='Use numpy acceleration (if available)')
    
    args = parser.parse_args()
    
    # Resolve circuit path
    circuit_base = Path(__file__).parent.parent / 'circuits' / args.circuit
    
    # Step 1: Import RGC
    t1 = time.time()
    try:
        details_path = circuit_base.parent / f"{circuit_base.name}_rgc_details.txt"
        circuit_path = circuit_base.parent / f"{circuit_base.name}_rgc.txt"
        input_path = circuit_base.parent / f"{circuit_base.name}_rgc_inputA.txt"
        
        if not details_path.exists():
            print(f"Error: RGC details file not found: {details_path}")
            return 1
        if not circuit_path.exists():
            print(f"Error: RGC circuit file not found: {circuit_path}")
            return 1
        if not input_path.exists():
            print(f"Error: RGC input file not found: {input_path}")
            return 1
        
        details = import_bristol_circuit_details(str(details_path), format='rgc')
        circuit = import_transformed_circuit(str(circuit_path), details)
        obfuscated_val_arr = import_obfuscated_input(str(input_path), details.bitlengthInputA)
        
    except Exception as e:
        print(f"Error importing RGC: {e}")
        return 1
    
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms importing")
    
    # Step 2: Parse input B
    try:
        inputB = parse_input(args.inputb, details.bitlengthInputB, args.circuit, 'B')
    except Exception as e:
        print(f"Error parsing input: {e}")
        return 1
    
    # Step 3: Evaluate CRGC
    t1 = time.time()
    if args.format == 'emp':
        output = evaluate_sorted_transformed_circuit(circuit, obfuscated_val_arr, inputB)
    else:
        output = evaluate_transformed_circuit(circuit, obfuscated_val_arr, inputB)
    elapsed_ms = int((time.time() - t1) * 1000)
    print(f"---TIMING--- {elapsed_ms}ms evaluate circuit")
    
    inA_int = bool_array_to_int(obfuscated_val_arr)
    inB_int = bool_array_to_int(inputB)
    out_int = bool_array_to_int(output)
    print(f"---Evaluation--- inA{inA_int}")
    print(f"---Evaluation--- inB{inB_int}")
    print(f"---Evaluation--- out{out_int}")
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
