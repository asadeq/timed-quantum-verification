#!/usr/bin/env python3
"""
Plot TLP Comprehensive Benchmark Results

Reads benchmark results from JSON files and creates plots showing
T iterations vs timing for setup, puzzle generation, and solving.
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path


def load_benchmark_results(results_dir="benchmark_results_T1_30"):
    """
    Load all benchmark results from JSON files
    
    Args:
        results_dir: Directory containing benchmark JSON files
    
    Returns:
        List of results sorted by T value
    """
    results_path = Path(results_dir)
    
    if not results_path.exists():
        raise FileNotFoundError(f"Results directory not found: {results_dir}")
    
    # Load summary statistics if available
    summary_file = results_path / "summary_statistics.json"
    if summary_file.exists():
        with open(summary_file, 'r') as f:
            summary_stats = json.load(f)
        
        # Sort by T value
        summary_stats.sort(key=lambda x: x['T'])
        return summary_stats
    else:
        # Load individual files if summary not available
        print("Summary file not found, loading individual JSON files...")
        results = []
        
        for json_file in results_path.glob("tlp_benchmark_T*.json"):
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            results.append({
                'T': data['config']['T'],
                'gates': data['circuit']['num_gates'],
                'wires': data['circuit']['num_wires'],
                'setup_ms': data['timing']['setup_total_ms'],
                'gen_avg_ms': data['timing']['generation']['avg_ms'],
                'gen_std_ms': data['timing']['generation']['std_ms'],
                'solve_avg_ms': data['timing']['solving']['avg_ms'],
                'solve_std_ms': data['timing']['solving']['std_ms'],
                'success_rate': data['summary']['success_rate']
            })
        
        # Sort by T value
        results.sort(key=lambda x: x['T'])
        return results


def plot_timing_breakdown(results, output_file="tlp_timing_breakdown.png"):
    """
    Create plot showing setup, generation, and solving times vs T
    
    Args:
        results: List of benchmark results
        output_file: Output filename for the plot
    """
    T_values = [r['T'] for r in results]
    setup_times = [r['setup_ms'] for r in results]
    gen_avg = [r['gen_avg_ms'] for r in results]
    gen_std = [r['gen_std_ms'] for r in results]
    solve_avg = [r['solve_avg_ms'] for r in results]
    solve_std = [r['solve_std_ms'] for r in results]
    
    fig, (ax1, ax2, ax3) = plt.subplots(1, 3, figsize=(18, 5))
    
    # Setup time
    ax1.plot(T_values, setup_times, marker='o', linewidth=2, markersize=6, color='#2E86AB')
    ax1.fill_between(T_values, setup_times, alpha=0.2, color='#2E86AB')
    ax1.set_xlabel('T (Iterations)', fontsize=12)
    ax1.set_ylabel('Setup Time (ms)', fontsize=12)
    ax1.set_title('Setup Time vs T\n(One-time garbling)', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    
    # Puzzle generation time
    ax2.errorbar(T_values, gen_avg, yerr=gen_std, marker='s', linewidth=2, 
                markersize=6, capsize=3, color='#A23B72')
    ax2.fill_between(T_values, 
                     np.array(gen_avg) - np.array(gen_std),
                     np.array(gen_avg) + np.array(gen_std),
                     alpha=0.2, color='#A23B72')
    ax2.set_xlabel('T (Iterations)', fontsize=12)
    ax2.set_ylabel('Generation Time (ms)', fontsize=12)
    ax2.set_title('Puzzle Generation Time vs T\n(Average ± Std)', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    # Puzzle solving time
    ax3.errorbar(T_values, solve_avg, yerr=solve_std, marker='^', linewidth=2, 
                markersize=6, capsize=3, color='#F18F01')
    ax3.fill_between(T_values, 
                     np.array(solve_avg) - np.array(solve_std),
                     np.array(solve_avg) + np.array(solve_std),
                     alpha=0.2, color='#F18F01')
    ax3.set_xlabel('T (Iterations)', fontsize=12)
    ax3.set_ylabel('Solving Time (ms)', fontsize=12)
    ax3.set_title('Puzzle Solving Time vs T\n(Average ± Std)', fontsize=14, fontweight='bold')
    ax3.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved timing breakdown plot: {output_file}")
    plt.close()


def plot_all_phases_combined(results, output_file="tlp_all_phases.png"):
    """
    Create plot showing all three phases on the same axes
    
    Args:
        results: List of benchmark results
        output_file: Output filename for the plot
    """
    T_values = [r['T'] for r in results]
    setup_times = [r['setup_ms'] for r in results]
    gen_avg = [r['gen_avg_ms'] for r in results]
    gen_std = [r['gen_std_ms'] for r in results]
    solve_avg = [r['solve_avg_ms'] for r in results]
    solve_std = [r['solve_std_ms'] for r in results]
    
    fig, ax = plt.subplots(figsize=(12, 7))
    
    ax.plot(T_values, setup_times, marker='o', linewidth=2, markersize=6, 
           label='Setup (one-time)', color='#2E86AB')
    ax.errorbar(T_values, gen_avg, yerr=gen_std, marker='s', linewidth=2, 
               markersize=6, capsize=3, label='Generation (avg ± std)', color='#A23B72')
    ax.errorbar(T_values, solve_avg, yerr=solve_std, marker='^', linewidth=2, 
               markersize=6, capsize=3, label='Solving (avg ± std)', color='#F18F01')
    
    ax.set_xlabel('T (Iterations)', fontsize=14)
    ax.set_ylabel('Time (ms)', fontsize=14)
    ax.set_title('TLP Performance: All Phases vs T', fontsize=16, fontweight='bold')
    ax.legend(fontsize=12, loc='best')
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved combined phases plot: {output_file}")
    plt.close()


def plot_circuit_size(results, output_file="tlp_circuit_size.png"):
    """
    Create plot showing circuit size (gates and wires) vs T
    
    Args:
        results: List of benchmark results
        output_file: Output filename for the plot
    """
    T_values = [r['T'] for r in results]
    gates = [r['gates'] for r in results]
    wires = [r['wires'] for r in results]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Gates
    ax1.plot(T_values, gates, marker='o', linewidth=2, markersize=6, color='#6A4C93')
    ax1.fill_between(T_values, gates, alpha=0.2, color='#6A4C93')
    ax1.set_xlabel('T (Iterations)', fontsize=12)
    ax1.set_ylabel('Number of Gates', fontsize=12)
    ax1.set_title('Circuit Size: Gates vs T', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    
    # Wires
    ax2.plot(T_values, wires, marker='s', linewidth=2, markersize=6, color='#1982C4')
    ax2.fill_between(T_values, wires, alpha=0.2, color='#1982C4')
    ax2.set_xlabel('T (Iterations)', fontsize=12)
    ax2.set_ylabel('Number of Wires', fontsize=12)
    ax2.set_title('Circuit Size: Wires vs T', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved circuit size plot: {output_file}")
    plt.close()


def plot_success_rate(results, output_file="tlp_success_rate.png"):
    """
    Create plot showing success rate vs T
    
    Args:
        results: List of benchmark results
        output_file: Output filename for the plot
    """
    T_values = [r['T'] for r in results]
    success_rates = [r['success_rate'] for r in results]
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    ax.plot(T_values, success_rates, marker='o', linewidth=2, markersize=8, color='#06A77D')
    ax.fill_between(T_values, success_rates, 100, alpha=0.2, color='#06A77D')
    ax.axhline(y=100, color='green', linestyle='--', linewidth=1, alpha=0.5, label='Perfect (100%)')
    
    ax.set_xlabel('T (Iterations)', fontsize=12)
    ax.set_ylabel('Success Rate (%)', fontsize=12)
    ax.set_title('Puzzle Success Rate vs T', fontsize=14, fontweight='bold')
    ax.set_ylim([0, 105])
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved success rate plot: {output_file}")
    plt.close()


def plot_time_per_iteration(results, output_file="tlp_time_per_iteration.png"):
    """
    Create plot showing time per iteration (normalized by T) for generation and solving
    
    Args:
        results: List of benchmark results
        output_file: Output filename for the plot
    """
    T_values = [r['T'] for r in results]
    gen_per_iter = [r['gen_avg_ms'] / r['T'] if r['T'] > 0 else 0 for r in results]
    solve_per_iter = [r['solve_avg_ms'] / r['T'] if r['T'] > 0 else 0 for r in results]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Generation time per iteration
    ax1.plot(T_values, gen_per_iter, marker='s', linewidth=2, markersize=6, color='#A23B72')
    ax1.set_xlabel('T (Iterations)', fontsize=12)
    ax1.set_ylabel('Time per Iteration (ms/T)', fontsize=12)
    ax1.set_title('Generation Time per Iteration', fontsize=14, fontweight='bold')
    ax1.grid(True, alpha=0.3)
    
    # Solving time per iteration
    ax2.plot(T_values, solve_per_iter, marker='^', linewidth=2, markersize=6, color='#F18F01')
    ax2.set_xlabel('T (Iterations)', fontsize=12)
    ax2.set_ylabel('Time per Iteration (ms/T)', fontsize=12)
    ax2.set_title('Solving Time per Iteration', fontsize=14, fontweight='bold')
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved time per iteration plot: {output_file}")
    plt.close()


def main():
    """Generate all plots from TLP benchmark results"""
    print("=" * 70)
    print("TLP COMPREHENSIVE BENCHMARK PLOTTING")
    print("=" * 70)
    
    # Load results
    print("\nLoading benchmark results...")
    try:
        results = load_benchmark_results()
        print(f"✓ Loaded results for T = 1 to {max(r['T'] for r in results)}")
        print(f"  Total configurations: {len(results)}")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please run benchmark_comprehensive.py first to generate results.")
        return
    
    # Create plots
    print("\nGenerating plots...")
    plot_timing_breakdown(results)
    plot_all_phases_combined(results)
    plot_circuit_size(results)
    plot_success_rate(results)
    plot_time_per_iteration(results)
    
    print("\n" + "=" * 70)
    print("All plots generated successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
