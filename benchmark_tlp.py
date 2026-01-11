#!/usr/bin/env python3
"""
Benchmark script for TLP protocol across different T values.
Runs the protocol for T from 1 to 100, with 5 trials each.
Saves timing data as JSON and generates a multi-line graph.
"""

import json
import time
import numpy as np
import matplotlib.pyplot as plt
from qiskit import QuantumCircuit
import secrets

from cvqc_protocol.ccy_protocol import Verifier, Prover
from cvqc_protocol.hamiltonian_compiler import HamiltonianCompiler
from timelock_puzzle.tlp_garbling import PythonGarbledTLP
from utils import random_oracle


def run_single_trial(T, circuit, secp=256):
    """Run a single trial of the protocol and return timing data."""
    
    # Compile circuit
    compiler = HamiltonianCompiler(circuit)
    hist_circuit = compiler.compile()
    
    # Setup TLP with specific T
    tlp = PythonGarbledTLP(T=T)
    
    # Time: Garbling setup
    garbling_start = time.time()
    pp = tlp.PSetup_Garble()
    garbling_time = time.time() - garbling_start
    
    # Run CCY phase 1
    ccy_verifier = Verifier()
    pk, sk = ccy_verifier.round1(hist_circuit, Q=16)
    
    # Hash concatenation
    r = secrets.token_bytes(secp // 8)
    d = random_oracle(str(sk["s"]) + str(int.from_bytes(r, "big")), secp // 8)
    
    # Time: Puzzle generation
    generation_start = time.time()
    puzzle = tlp.PGen(sk["s"], pp)
    generation_time = time.time() - generation_start
    
    # Time: Reveal/Solve
    reveal_start = time.time()
    y = tlp.PSolve(puzzle, pp)
    reveal_time = time.time() - reveal_start
    
    return {
        'garbling_time': garbling_time,
        'generation_time': generation_time,
        'reveal_time': reveal_time
    }


def run_benchmark(T_min=10, T_max=10, trials=5):
    """Run benchmark across T values."""
    
    print("="*60)
    print("TLP BENCHMARK")
    print("="*60)
    print(f"T range: {T_min} to {T_max}")
    print(f"Trials per T: {trials}")
    print("="*60)
    
    # Create test circuit
    circuit = QuantumCircuit(2)
    circuit.h(0)
    circuit.cx(0, 1)
    
    results = {
        'T_values': [],
        'garbling_times': [],
        'generation_times': [],
        'reveal_times': []
    }
    
    for T in range(T_min, T_max + 1):
        print(f"\nTesting T={T}...", end=" ", flush=True)
        
        trial_garbling = []
        trial_generation = []
        trial_reveal = []
        
        for trial in range(trials):
            try:
                timing = run_single_trial(T, circuit)
                trial_garbling.append(timing['garbling_time'])
                trial_generation.append(timing['generation_time'])
                trial_reveal.append(timing['reveal_time'])
                print(f".", end="", flush=True)
            except Exception as e:
                print(f"\nError in trial {trial+1} for T={T}: {e}")
                continue
        
        if trial_garbling:  # If we have at least one successful trial
            # Store average times
            results['T_values'].append(T)
            results['garbling_times'].append(np.mean(trial_garbling))
            results['generation_times'].append(np.mean(trial_generation))
            results['reveal_times'].append(np.mean(trial_reveal))
            print(f" Done! (avg: {np.mean(trial_garbling):.3f}s / {np.mean(trial_generation):.3f}s / {np.mean(trial_reveal):.3f}s)")
        else:
            print(f" Failed!")
    
    return results


def save_results(results, filename='tlp_benchmark_results.json'):
    """Save results to JSON file."""
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n✓ Results saved to {filename}")


def plot_results(results, filename='tlp_benchmark_plot.png'):
    """Generate multi-line plot."""
    
    plt.figure(figsize=(12, 7))
    
    T_values = results['T_values']
    
    # Plot three lines
    plt.plot(T_values, results['garbling_times'], 'b-o', 
             label='Garbling Setup', linewidth=2, markersize=4)
    plt.plot(T_values, results['generation_times'], 'r-s', 
             label='Puzzle Generation', linewidth=2, markersize=4)
    plt.plot(T_values, results['reveal_times'], 'g-^', 
             label='Reveal/Solve Phase', linewidth=2, markersize=4)
    
    plt.xlabel('T (Time Parameter)', fontsize=12)
    plt.ylabel('Time (seconds)', fontsize=12)
    plt.title('TLP Protocol Performance vs Time Parameter T', fontsize=14, fontweight='bold')
    plt.legend(fontsize=10)
    plt.grid(True, alpha=0.3)
    
    # Add minor gridlines
    plt.grid(True, which='minor', alpha=0.1)
    plt.minorticks_on()
    
    plt.tight_layout()
    plt.savefig(filename, dpi=300, bbox_inches='tight')
    print(f"✓ Plot saved to {filename}")
    
    # Also show the plot
    plt.show()


if __name__ == "__main__":
    # Run benchmark
    results = run_benchmark(T_min=1, T_max=100, trials=5)
    
    # Save results
    save_results(results)
    
    # Generate plot
    plot_results(results)
    
    print("\n" + "="*60)
    print("BENCHMARK COMPLETE")
    print("="*60)
