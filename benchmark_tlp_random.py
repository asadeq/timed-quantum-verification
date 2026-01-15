#!/usr/bin/env python3
"""
Comprehensive TLP Benchmark Script

Runs benchmarks for T values from 1 to 30 with 20 puzzles each.
Stores detailed results in separate JSON files and computes statistics.
"""

import time
import secrets
import json
import statistics
from pathlib import Path
from timelock_puzzle.tlp_garbling import PythonGarbledTLP


def format_time(ms):
    """Format milliseconds into readable string"""
    if ms < 1:
        return f"{ms*1000:.2f} μs"
    elif ms < 1000:
        return f"{ms:.2f} ms"
    else:
        return f"{ms/1000:.2f} s"


def run_benchmark_for_T(T, lam=256, num_puzzles=20):
    """
    Run complete benchmark for a specific T value.
    
    Args:
        T: Number of iterations
        lam: Security parameter (default: 256)
        num_puzzles: Number of puzzles to generate and solve (default: 20)
    
    Returns:
        Dictionary with detailed results including all individual puzzle timings
    """
    print(f"\n{'='*70}")
    print(f"Benchmarking T={T} (λ={lam}, SHA-256, n={num_puzzles} puzzles)")
    print(f"{'='*70}")
    
    # Phase 1: Setup
    print(f"\n[1/3] Setup Phase")
    
    # Create circuit (includes loading SHA-256 Bristol file)
    circuit_start = time.perf_counter()
    tlp = PythonGarbledTLP(lam=lam, T=T, use_sha256=True)
    circuit_time = (time.perf_counter() - circuit_start) * 1000
    
    # Garble circuit (PSetup)
    garble_start = time.perf_counter()
    pp = tlp.PSetup_Garble()
    garble_time = (time.perf_counter() - garble_start) * 1000
    
    setup_time = circuit_time + garble_time
    
    print(f"  Circuit: {tlp.circuit.details.numGates:,} gates, {tlp.circuit.details.numWires:,} wires")
    print(f"  Circuit creation: {format_time(circuit_time)}")
    print(f"  Garbling (PSetup): {format_time(garble_time)}")
    print(f"  Total setup: {format_time(setup_time)}")
    
    # Phase 2: Generate Puzzles
    print(f"\n[2/3] Puzzle Generation (n={num_puzzles})")
    test_secrets = [secrets.randbelow(2) for _ in range(num_puzzles)]
    puzzles = []
    gen_times = []
    
    for i, secret in enumerate(test_secrets, 1):
        gen_start = time.perf_counter()
        puzzle_Z = tlp.PGen(secret, pp)
        gen_time = (time.perf_counter() - gen_start) * 1000
        gen_times.append(gen_time)
        puzzles.append((secret, puzzle_Z))
        
        if i % 5 == 0 or i == num_puzzles:
            print(f"  Progress: {i}/{num_puzzles} puzzles generated")
    
    # Phase 3: Solve Puzzles
    print(f"\n[3/3] Puzzle Solving (n={num_puzzles})")
    solve_times = []
    puzzle_results = []
    
    for i, (original_secret, puzzle_Z) in enumerate(puzzles, 1):
        solve_start = time.perf_counter()
        recovered = tlp.PSolve(puzzle_Z, pp)
        solve_time = (time.perf_counter() - solve_start) * 1000
        solve_times.append(solve_time)
        
        success = (recovered == original_secret)
        puzzle_results.append({
            'puzzle_id': i,
            'original_secret': original_secret,
            'recovered_secret': recovered,
            'success': success,
            'gen_time_ms': gen_time,
            'solve_time_ms': solve_time
        })
        
        if i % 5 == 0 or i == num_puzzles:
            print(f"  Progress: {i}/{num_puzzles} puzzles solved")
    
    # Compute statistics
    success_count = sum(1 for p in puzzle_results if p['success'])
    success_rate = (success_count / len(puzzle_results)) * 100
    
    avg_gen = statistics.mean(gen_times)
    std_gen = statistics.stdev(gen_times) if len(gen_times) > 1 else 0.0
    
    avg_solve = statistics.mean(solve_times)
    std_solve = statistics.stdev(solve_times) if len(solve_times) > 1 else 0.0
    
    # Summary
    print(f"\n{'─'*70}")
    print(f"Results Summary:")
    print(f"  Success rate: {success_rate:.1f}% ({success_count}/{len(puzzle_results)})")
    print(f"  Setup time: {format_time(setup_time)}")
    print(f"  Generation: {format_time(avg_gen)} ± {format_time(std_gen)}")
    print(f"  Solving: {format_time(avg_solve)} ± {format_time(std_solve)}")
    
    # Compile complete results
    results = {
        'config': {
            'T': T,
            'lambda': lam,
            'algorithm': 'SHA-256',
            'num_puzzles': num_puzzles
        },
        'circuit': {
            'num_gates': tlp.circuit.details.numGates,
            'num_wires': tlp.circuit.details.numWires
        },
        'timing': {
            'circuit_creation_ms': circuit_time,
            'garbling_ms': garble_time,
            'setup_total_ms': setup_time,
            'generation': {
                'times_ms': gen_times,
                'avg_ms': avg_gen,
                'std_ms': std_gen,
                'min_ms': min(gen_times),
                'max_ms': max(gen_times)
            },
            'solving': {
                'times_ms': solve_times,
                'avg_ms': avg_solve,
                'std_ms': std_solve,
                'min_ms': min(solve_times),
                'max_ms': max(solve_times)
            }
        },
        'puzzles': puzzle_results,
        'summary': {
            'success_count': success_count,
            'success_rate': success_rate,
            'total_time_ms': setup_time + sum(gen_times) + sum(solve_times)
        }
    }
    
    return results


def main():
    """Run comprehensive benchmark for T from 1 to 30"""
    print("#" * 70)
    print("# COMPREHENSIVE TLP BENCHMARK")
    print("#" * 70)
    print("\nRunning benchmarks for T ∈ [1, 30] with 20 puzzles each")
    print("Algorithm: SHA-256")
    print("Security parameter: λ = 256 bits")
    print("\n" + "#" * 70)
    
    # Create output directory
    output_dir = Path("benchmark_results_T1_30")
    output_dir.mkdir(exist_ok=True)
    print(f"\nResults will be saved to: {output_dir}/")
    
    # Store summary statistics for all T values
    summary_stats = []
    
    # Run benchmarks for T from 1 to 30
    T_range = range(1, 31)
    total_experiments = len(T_range)
    
    for idx, T in enumerate(T_range, 1):
        print(f"\n{'=' * 70}")
        print(f"EXPERIMENT {idx}/{total_experiments}: T = {T}")
        print(f"{'=' * 70}")
        
        # Run benchmark
        results = run_benchmark_for_T(T=T, lam=256, num_puzzles=20)
        
        # Save detailed results to JSON file
        output_file = output_dir / f"tlp_benchmark_T{T}.json"
        with open(output_file, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n Saved detailed results to: {output_file}")
        
        # Collect summary statistics
        summary_stats.append({
            'T': T,
            'gates': results['circuit']['num_gates'],
            'wires': results['circuit']['num_wires'],
            'setup_ms': results['timing']['setup_total_ms'],
            'gen_avg_ms': results['timing']['generation']['avg_ms'],
            'gen_std_ms': results['timing']['generation']['std_ms'],
            'solve_avg_ms': results['timing']['solving']['avg_ms'],
            'solve_std_ms': results['timing']['solving']['std_ms'],
            'success_rate': results['summary']['success_rate']
        })
    
    # Save summary statistics
    summary_file = output_dir / "summary_statistics.json"
    with open(summary_file, 'w') as f:
        json.dump(summary_stats, f, indent=2)
    
    # Display final summary table
    print("\n\n" + "=" * 100)
    print("FINAL BENCHMARK SUMMARY")
    print("=" * 100)
    print(f"\n{'T':>3} | {'Gates':>10} | {'Setup':>12} | {'Gen (Avg±Std)':>20} | {'Solve (Avg±Std)':>20} | {'Success':>8}")
    print("─" * 100)
    
    for stat in summary_stats:
        gen_str = f"{format_time(stat['gen_avg_ms'])} ± {format_time(stat['gen_std_ms'])}"
        solve_str = f"{format_time(stat['solve_avg_ms'])} ± {format_time(stat['solve_std_ms'])}"
        print(f"{stat['T']:>3} | {stat['gates']:>10,} | {format_time(stat['setup_ms']):>12} | "
              f"{gen_str:>20} | {solve_str:>20} | {stat['success_rate']:>7.1f}%")
    


if __name__ == "__main__":
    main()
