#!/usr/bin/env python3
"""
Qiskit Random Circuit Execution Benchmark

Measures execution time for random Qiskit circuits of varying sizes.
Benchmarks 5-qubit and 10-qubit circuits at depths 10, 20, 30, ..., 100.
Runs 10 trials for each configuration.
"""

import time
import json
import statistics
from pathlib import Path
from qiskit.circuit.random import random_circuit
from qiskit import transpile
from qiskit_aer import AerSimulator


def format_time(ms):
    """Format milliseconds into readable string"""
    if ms < 1:
        return f"{ms*1000:.2f} μs"
    elif ms < 1000:
        return f"{ms:.2f} ms"
    else:
        return f"{ms/1000:.2f} s"


def generate_random_qiskit_circuit(num_qubits, depth):
    """
    Generate a random Qiskit circuit with measurements
    
    Args:
        num_qubits: Number of qubits
        depth: Circuit depth
    
    Returns:
        Qiskit QuantumCircuit
    """
    circuit = random_circuit(num_qubits=num_qubits, depth=depth, seed=None)
    circuit.measure_all()
    return circuit


def run_single_trial(num_qubits, depth, trial_num, shots=1024):
    """
    Run a single trial for a given circuit configuration
    
    Args:
        num_qubits: Number of qubits in the circuit
        depth: Depth of the circuit
        trial_num: Trial number (for logging)
        shots: Number of shots for circuit execution (default: 1024)
    
    Returns:
        Dictionary with timing results for this trial
    """
    print(f"  Trial {trial_num}/10: ", end='', flush=True)
    
    # Generate random Qiskit circuit
    circuit_gen_start = time.perf_counter()
    qiskit_circuit = generate_random_qiskit_circuit(num_qubits, depth)
    circuit_gen_time = (time.perf_counter() - circuit_gen_start) * 1000
    
    # Get circuit properties
    num_gates = qiskit_circuit.size()
    circuit_depth = qiskit_circuit.depth()
    
    # Transpile circuit for execution with optimization_level=0 to avoid issues
    transpile_start = time.perf_counter()
    simulator = AerSimulator()
    try:
        transpiled_circuit = transpile(qiskit_circuit, simulator, optimization_level=0)
        transpile_time = (time.perf_counter() - transpile_start) * 1000
    except Exception as e:
        # If transpilation fails, use the circuit as-is
        print(f"Transpilation failed ({e.__class__.__name__}), using original circuit")
        transpiled_circuit = qiskit_circuit
        transpile_time = (time.perf_counter() - transpile_start) * 1000
    
    # Execute circuit
    execute_start = time.perf_counter()
    job = simulator.run(transpiled_circuit, shots=shots)
    result = job.result()
    execute_time = (time.perf_counter() - execute_start) * 1000
    
    # Get counts to verify execution
    counts = result.get_counts()
    num_unique_outcomes = len(counts)
    
    total_time = circuit_gen_time + transpile_time + execute_time
    
    print(f"Gen={format_time(circuit_gen_time)}, Transpile={format_time(transpile_time)}, "
          f"Execute={format_time(execute_time)}, Total={format_time(total_time)}")
    
    return {
        'trial': trial_num,
        'circuit': {
            'num_qubits': num_qubits,
            'depth': circuit_depth,
            'num_gates': num_gates,
            'num_unique_outcomes': num_unique_outcomes
        },
        'timing': {
            'generation_ms': circuit_gen_time,
            'transpile_ms': transpile_time,
            'execution_ms': execute_time,
            'total_ms': total_time
        }
    }


def run_benchmark_for_config(num_qubits, depth, num_trials=10):
    """
    Run complete benchmark for a specific qubit/depth configuration
    
    Args:
        num_qubits: Number of qubits
        depth: Circuit depth
        num_trials: Number of trials to run (default: 10)
    
    Returns:
        Dictionary with aggregated results and statistics
    """
    print(f"\n{'='*70}")
    print(f"Configuration: {num_qubits} qubits, depth {depth} ({num_trials} trials)")
    print(f"{'='*70}")
    
    trial_results = []
    
    # Run all trials
    for trial_num in range(1, num_trials + 1):
        trial_data = run_single_trial(num_qubits, depth, trial_num)
        trial_results.append(trial_data)
    
    # Aggregate statistics across all trials
    all_gen_times = [t['timing']['generation_ms'] for t in trial_results]
    all_transpile_times = [t['timing']['transpile_ms'] for t in trial_results]
    all_execute_times = [t['timing']['execution_ms'] for t in trial_results]
    all_total_times = [t['timing']['total_ms'] for t in trial_results]
    
    # Get average circuit properties
    avg_gates = statistics.mean([t['circuit']['num_gates'] for t in trial_results])
    avg_circuit_depth = statistics.mean([t['circuit']['depth'] for t in trial_results])
    
    # Compute statistics
    stats = {
        'generation': {
            'avg_ms': statistics.mean(all_gen_times),
            'std_ms': statistics.stdev(all_gen_times) if len(all_gen_times) > 1 else 0.0,
            'min_ms': min(all_gen_times),
            'max_ms': max(all_gen_times)
        },
        'transpile': {
            'avg_ms': statistics.mean(all_transpile_times),
            'std_ms': statistics.stdev(all_transpile_times) if len(all_transpile_times) > 1 else 0.0,
            'min_ms': min(all_transpile_times),
            'max_ms': max(all_transpile_times)
        },
        'execution': {
            'avg_ms': statistics.mean(all_execute_times),
            'std_ms': statistics.stdev(all_execute_times) if len(all_execute_times) > 1 else 0.0,
            'min_ms': min(all_execute_times),
            'max_ms': max(all_execute_times)
        },
        'total': {
            'avg_ms': statistics.mean(all_total_times),
            'std_ms': statistics.stdev(all_total_times) if len(all_total_times) > 1 else 0.0,
            'min_ms': min(all_total_times),
            'max_ms': max(all_total_times)
        }
    }
    
    # Print summary
    print(f"\n{'─'*70}")
    print(f"Summary Statistics (n={num_trials} trials):")
    print(f"  Circuit: ~{avg_gates:.0f} gates, depth ~{avg_circuit_depth:.0f}")
    print(f"  Generation:  {format_time(stats['generation']['avg_ms'])} ± {format_time(stats['generation']['std_ms'])}")
    print(f"  Transpile:   {format_time(stats['transpile']['avg_ms'])} ± {format_time(stats['transpile']['std_ms'])}")
    print(f"  Execution:   {format_time(stats['execution']['avg_ms'])} ± {format_time(stats['execution']['std_ms'])}")
    print(f"  Total:       {format_time(stats['total']['avg_ms'])} ± {format_time(stats['total']['std_ms'])}")
    
    return {
        'config': {
            'num_qubits': num_qubits,
            'depth': depth,
            'num_trials': num_trials,
            'shots': 1024
        },
        'circuit': {
            'avg_gates': avg_gates,
            'avg_depth': avg_circuit_depth
        },
        'statistics': stats,
        'trials': trial_results
    }


def main():
    """Run comprehensive Qiskit random circuit benchmark"""
    print("#" * 70)
    print("# QISKIT RANDOM CIRCUIT EXECUTION BENCHMARK")
    print("#" * 70)
    print("\nBenchmarking Qiskit random circuit execution times")
    print("Configurations:")
    print("  - Qubits: 5, 10")
    print("  - Depths: 10, 20, 30, 40, 50, 60, 70, 80, 90, 100")
    print("  - Trials: 10 per configuration")
    print("  - Shots: 1024 per circuit")
    print("\n" + "#" * 70)
    
    # Create output directory
    output_dir = Path("benchmark_results_qiskit_random")
    output_dir.mkdir(exist_ok=True)
    print(f"\nResults will be saved to: {output_dir}/")
    
    # Configuration
    qubit_counts = [5, 10, 15]
    depths = list(range(10, 301, 10))  # 10, 20, 30, ..., 200
    num_trials = 20
    
    # Store all results
    all_results = []
    summary_stats = []
    
    total_configs = len(qubit_counts) * len(depths)
    config_num = 0
    
    # Run benchmarks for all configurations
    for num_qubits in qubit_counts:
        for depth in depths:
            config_num += 1
            print(f"\n{'=' * 70}")
            print(f"EXPERIMENT {config_num}/{total_configs}")
            print(f"{'=' * 70}")
            
            # Run benchmark
            results = run_benchmark_for_config(num_qubits, depth, num_trials)
            all_results.append(results)
            
            # Save individual configuration results
            output_file = output_dir / f"qiskit_q{num_qubits}_d{depth}.json"
            with open(output_file, 'w') as f:
                json.dump(results, f, indent=2)
            print(f"\n✓ Saved to: {output_file}")
            
            # Collect summary statistics
            summary_stats.append({
                'qubits': num_qubits,
                'depth': depth,
                'avg_gates': results['circuit']['avg_gates'],
                'avg_circuit_depth': results['circuit']['avg_depth'],
                'gen_avg_ms': results['statistics']['generation']['avg_ms'],
                'gen_std_ms': results['statistics']['generation']['std_ms'],
                'transpile_avg_ms': results['statistics']['transpile']['avg_ms'],
                'transpile_std_ms': results['statistics']['transpile']['std_ms'],
                'execute_avg_ms': results['statistics']['execution']['avg_ms'],
                'execute_std_ms': results['statistics']['execution']['std_ms'],
                'total_avg_ms': results['statistics']['total']['avg_ms'],
                'total_std_ms': results['statistics']['total']['std_ms']
            })
    
    # Save complete results
    complete_file = output_dir / "all_results.json"
    with open(complete_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    # Save summary statistics
    summary_file = output_dir / "summary_statistics.json"
    with open(summary_file, 'w') as f:
        json.dump(summary_stats, f, indent=2)
    
    # Display final summary tables
    print("\n\n" + "=" * 90)
    print("FINAL BENCHMARK SUMMARY")
    print("=" * 90)
    
    for num_qubits in qubit_counts:
        print(f"\n{num_qubits}-QUBIT CIRCUITS:")
        print(f"{'Depth':>5} | {'Gates':>8} | {'Transpile (Avg±Std)':>20} | "
              f"{'Execute (Avg±Std)':>20} | {'Total (Avg±Std)':>20}")
        print("─" * 90)
        
        qubit_stats = [s for s in summary_stats if s['qubits'] == num_qubits]
        for stat in qubit_stats:
            transpile_str = f"{format_time(stat['transpile_avg_ms'])} ± {format_time(stat['transpile_std_ms'])}"
            execute_str = f"{format_time(stat['execute_avg_ms'])} ± {format_time(stat['execute_std_ms'])}"
            total_str = f"{format_time(stat['total_avg_ms'])} ± {format_time(stat['total_std_ms'])}"
            print(f"{stat['depth']:>5} | {stat['avg_gates']:>8.0f} | {transpile_str:>20} | "
                  f"{execute_str:>20} | {total_str:>20}")
    



if __name__ == "__main__":
    main()
