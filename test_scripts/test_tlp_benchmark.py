#!/usr/bin/env python3
"""
TLP Benchmark Test Script

Tests the Time-Lock Puzzle implementation with various parameters
and measures performance for setup, puzzle generation, and solving.
"""

import time
import secrets
from pathlib import Path
from timelock_puzzle.tlp_garbling import PythonGarbledTLP
from crgc_garbled_circuits.circuit_writer import export_circuit_separate_files, export_obfuscated_input


def format_time(ms):
    """Format milliseconds into readable string"""
    if ms < 1:
        return f"{ms*1000:.2f} μs"
    elif ms < 1000:
        return f"{ms:.2f} ms"
    else:
        return f"{ms/1000:.2f} s"


def save_circuits(tlp, pp, output_dir="tlp_circuits"):
    """
    Save original ungarbled circuit and garbled circuit files
    
    Args:
        tlp: PythonGarbledTLP instance
        pp: Public parameters (C̃, pk) from PSetup
        output_dir: Directory to save circuits (default: tlp_circuits)
    
    Saves:
        - original_circuit.txt: Ungarbled circuit in Bristol format
        - garbled_circuit_rgc.txt: Garbled circuit gates
        - garbled_circuit_rgc_details.txt: Circuit metadata
        - garbled_circuit_rgc_inputA.txt: Base flip pattern for input encoding
    """
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    C_tilde, pk = pp
    base_flipped = pk['base_flipped']
    
    # Get mode string for filename
    mode = "sha256" if tlp.use_sha256 else "xor"
    prefix = f"{mode}_T{tlp.T}"
    
    # Save original ungarbled circuit in Bristol format
    original_file = output_path / f"{prefix}_original_circuit.txt"
    with open(original_file, 'w') as f:
        # Header line 1: numGates numWires
        f.write(f"{tlp.circuit.details.numGates} {tlp.circuit.details.numWires}\n")
        
        # Header line 2: numInputs bitlengthInputA bitlengthInputB
        f.write(f"2 {tlp.circuit.details.bitlengthInputA} {tlp.circuit.details.bitlengthInputB}\n")
        
        # Header line 3: numOutputs bitlengthOutputs
        f.write(f"{tlp.circuit.details.numOutputs} {tlp.circuit.details.bitlengthOutputs}\n")
        
        # Gates
        for gate in tlp.circuit.gates:
            # Convert truth table to gate type
            tt = gate.truthTable
            if tt == [[False, True], [True, False]]:
                gate_type = "XOR"
            elif tt == [[False, False], [False, True]]:
                gate_type = "AND"
            elif tt == [[False, True], [True, True]]:
                gate_type = "OR"
            else:
                gate_type = "UNKNOWN"
            
            f.write(f"2 1 {gate.leftParentID} {gate.rightParentID} {gate.outputID} {gate_type}\n")
    
    print(f"  ✓ Saved original circuit: {original_file}")
    
    # Save garbled circuit RGC files
    circuit_name = output_path / prefix
    
    # Export garbled circuit using CRGC's export functions
    export_circuit_separate_files(C_tilde, circuit_name)
    print(f"  ✓ Saved garbled circuit: {circuit_name}_rgc.txt")
    print(f"  ✓ Saved circuit details: {circuit_name}_rgc_details.txt")
    
    # Export base flip pattern as inputA
    export_obfuscated_input(base_flipped, C_tilde.details, circuit_name)
    print(f"  ✓ Saved base flip pattern: {circuit_name}_rgc_inputA.txt")
    
    print(f"\n  All circuits saved to: {output_path}/")
    return str(output_path)


def test_configuration(T, lam, use_sha256, num_puzzles=5, save_circuit=False):
    """
    Test a specific TLP configuration
    
    Args:
        T: Number of iterations
        lam: Security parameter (bits)
        use_sha256: Use SHA-256 or XOR mixing
        num_puzzles: Number of puzzles to generate and solve
        save_circuit: If True, save original and garbled circuits to disk
    """
    mode = "SHA-256" if use_sha256 else "XOR-mixing"
    print(f"\n{'='*70}")
    print(f"Configuration: T={T}, λ={lam}, Mode={mode}")
    print(f"{'='*70}")
    
    # Phase 1: Setup
    print(f"\n[1/3] Setup Phase")
    
    # Create circuit (includes loading SHA-256 Bristol file if needed)
    circuit_start = time.perf_counter()
    tlp = PythonGarbledTLP(lam=lam, T=T, use_sha256=use_sha256)
    circuit_time = (time.perf_counter() - circuit_start) * 1000
    
    # Garble circuit (PSetup)
    garble_start = time.perf_counter()
    pp = tlp.PSetup_Garble()
    garble_time = (time.perf_counter() - garble_start) * 1000
    
    setup_time = circuit_time + garble_time
    
    print(f"  Circuit: {tlp.circuit.details.numGates:,} gates, {tlp.circuit.details.numWires:,} wires")
    print(f"  Circuit creation: {format_time(circuit_time)}")
    print(f"  Garbling (PSetup): {format_time(garble_time)}")
    print(f"  Total setup time: {format_time(setup_time)}")
    
    # Save circuits if requested
    if save_circuit:
        print(f"\n[Saving Circuits]")
        save_circuits(tlp, pp)
    
    # Phase 2: Generate Puzzles
    print(f"\n[2/3] Puzzle Generation (n={num_puzzles})")
    test_secrets = [secrets.randbelow(2) for _ in range(num_puzzles)]
    puzzles = []
    gen_times = []
    
    for i, secret in enumerate(test_secrets):
        gen_start = time.perf_counter()
        puzzle_Z = tlp.PGen(secret, pp)
        gen_time = (time.perf_counter() - gen_start) * 1000
        gen_times.append(gen_time)
        puzzles.append((secret, puzzle_Z))
        print(f"  Puzzle {i+1}: secret={secret}, time={format_time(gen_time)}")
    
    avg_gen = sum(gen_times) / len(gen_times)
    print(f"  Average: {format_time(avg_gen)}")
    
    # Phase 3: Solve Puzzles
    print(f"\n[3/3] Puzzle Solving")
    solve_times = []
    results = []
    
    for i, (original_secret, puzzle_Z) in enumerate(puzzles):
        solve_start = time.perf_counter()
        recovered = tlp.PSolve_Garbled(puzzle_Z, pp)
        solve_time = (time.perf_counter() - solve_start) * 1000
        solve_times.append(solve_time)
        
        success = (recovered == original_secret)
        results.append(success)
        status = "✓" if success else "✗"
        print(f"  Puzzle {i+1}: {status} original={original_secret}, recovered={recovered}, time={format_time(solve_time)}")
    
    avg_solve = sum(solve_times) / len(solve_times)
    success_rate = sum(results) / len(results) * 100
    
    # Summary
    print(f"\n{'─'*70}")
    print(f"Summary:")
    print(f"  Success rate: {success_rate:.0f}% ({sum(results)}/{len(results)})")
    print(f"  Avg generation: {format_time(avg_gen)}")
    print(f"  Avg solving: {format_time(avg_solve)}")
    print(f"  Total time: {format_time(setup_time + sum(gen_times) + sum(solve_times))}")
    print(f"    - Setup: {format_time(setup_time)} (one-time)")
    print(f"    - Generation: {format_time(sum(gen_times))} ({num_puzzles} puzzles)")
    print(f"    - Solving: {format_time(sum(solve_times))} ({num_puzzles} puzzles)")
    
    return {
        'config': f"T={T}, λ={lam}, {mode}",
        'success_rate': success_rate,
        'setup_time': setup_time,
        'avg_gen_time': avg_gen,
        'avg_solve_time': avg_solve,
        'gates': tlp.circuit.details.numGates,
        'wires': tlp.circuit.details.numWires
    }


def main():
    """Run benchmark tests with different configurations"""
    print("#" * 70)
    print("# TLP BENCHMARK TEST SUITE")
    print("#" * 70)
    print("\nTesting Time-Lock Puzzle implementation with various configurations")
    print("Measures setup, generation, and solving times\n")
    
    all_results = []
    
    # Test 1: Small circuit with XOR mixing (fast baseline)
    print("\n" + "█" * 70)
    print("TEST 1: Small circuit, XOR mixing (baseline)")
    print("█" * 70)
    result = test_configuration(T=2, lam=256, use_sha256=False, num_puzzles=10, save_circuit=False)
    all_results.append(result)
    
    # Test 2: Small circuit with SHA-256 (cryptographic)
    print("\n" + "█" * 70)
    print("TEST 2: Small circuit, SHA-256 (cryptographic)")
    print("█" * 70)
    result = test_configuration(T=5, lam=256, use_sha256=True, num_puzzles=30, save_circuit=False)
    all_results.append(result)
    
    # Test 3: Medium circuit with XOR mixing
    # print("\n" + "█" * 70)
    # print("TEST 3: Medium circuit, XOR mixing")
    # print("█" * 70)
    # result = test_configuration(T=4, lam=256, use_sha256=False, num_puzzles=5)
    # all_results.append(result)
    
    # Final Comparison
    print("\n" + "=" * 70)
    print("BENCHMARK COMPARISON")
    print("=" * 70)
    print(f"\n{'Configuration':<35} | {'Gates':>10} | {'Avg Gen':>10} | {'Avg Solve':>10} | {'Success':>8}")
    print("─" * 70)
    
    for r in all_results:
        print(f"{r['config']:<35} | {r['gates']:>10,} | {format_time(r['avg_gen_time']):>10} | "
              f"{format_time(r['avg_solve_time']):>10} | {r['success_rate']:>7.0f}%")
    

if __name__ == "__main__":
    main()
