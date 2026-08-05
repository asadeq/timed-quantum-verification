#!/usr/bin/env python3
"""
Plot Qiskit Random Circuit Benchmark Results

Reads benchmark results from JSON files and creates plots showing
circuit depth vs execution time for different qubit counts.
"""

import json
import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path


def load_benchmark_results(results_dir="benchmark_results_qiskit_random"):
    """
    Load all benchmark results from JSON files
    
    Args:
        results_dir: Directory containing benchmark JSON files
    
    Returns:
        Dictionary organized by qubit count and depth
    """
    results_path = Path(results_dir)
    
    if not results_path.exists():
        raise FileNotFoundError(f"Results directory not found: {results_dir}")
    
    # Load summary statistics if available
    summary_file = results_path / "summary_statistics.json"
    if summary_file.exists():
        with open(summary_file, 'r') as f:
            summary_stats = json.load(f)
        
        # Organize by qubit count
        results_by_qubits = {}
        for stat in summary_stats:
            qubits = stat['qubits']
            if qubits not in results_by_qubits:
                results_by_qubits[qubits] = []
            results_by_qubits[qubits].append(stat)
        
        # Sort by depth
        for qubits in results_by_qubits:
            results_by_qubits[qubits].sort(key=lambda x: x['depth'])
        
        return results_by_qubits
    else:
        # Load individual files if summary not available
        print("Summary file not found, loading individual JSON files...")
        results_by_qubits = {}
        
        for json_file in results_path.glob("qiskit_q*_d*.json"):
            with open(json_file, 'r') as f:
                data = json.load(f)
            
            qubits = data['config']['num_qubits']
            depth = data['config']['depth']
            
            if qubits not in results_by_qubits:
                results_by_qubits[qubits] = []
            
            results_by_qubits[qubits].append({
                'depth': depth,
                'avg_gates': data['circuit']['avg_gates'],
                'avg_circuit_depth': data['circuit']['avg_depth'],
                'gen_avg_ms': data['statistics']['generation']['avg_ms'],
                'gen_std_ms': data['statistics']['generation']['std_ms'],
                'transpile_avg_ms': data['statistics']['transpile']['avg_ms'],
                'transpile_std_ms': data['statistics']['transpile']['std_ms'],
                'execute_avg_ms': data['statistics']['execution']['avg_ms'],
                'execute_std_ms': data['statistics']['execution']['std_ms'],
                'total_avg_ms': data['statistics']['total']['avg_ms'],
                'total_std_ms': data['statistics']['total']['std_ms']
            })
        
        # Sort by depth
        for qubits in results_by_qubits:
            results_by_qubits[qubits].sort(key=lambda x: x['depth'])
        
        return results_by_qubits


def plot_timing_breakdown(results_by_qubits, output_file="qiskit_timing_breakdown.png"):
    """
    Create plots showing timing breakdown for each qubit count
    
    Args:
        results_by_qubits: Dictionary of results organized by qubit count
        output_file: Output filename for the plot
    """
    qubit_counts = sorted(results_by_qubits.keys())
    n_plots = len(qubit_counts)
    
    fig, axes = plt.subplots(1, n_plots, figsize=(7*n_plots, 6))
    if n_plots == 1:
        axes = [axes]
    
    for idx, qubits in enumerate(qubit_counts):
        ax = axes[idx]
        data = results_by_qubits[qubits]
        
        depths = [d['depth'] for d in data]
        gen_times = [d['gen_avg_ms'] for d in data]
        transpile_times = [d['transpile_avg_ms'] for d in data]
        execute_times = [d['execute_avg_ms'] for d in data]
        total_times = [d['total_avg_ms'] for d in data]
        
        # Plot with error bars
        gen_std = [d['gen_std_ms'] for d in data]
        transpile_std = [d['transpile_std_ms'] for d in data]
        execute_std = [d['execute_std_ms'] for d in data]
        total_std = [d['total_std_ms'] for d in data]
        
        ax.errorbar(depths, gen_times, yerr=gen_std, marker='o', label='Generation', capsize=3, alpha=0.7)
        ax.errorbar(depths, transpile_times, yerr=transpile_std, marker='s', label='Transpile', capsize=3, alpha=0.7)
        ax.errorbar(depths, execute_times, yerr=execute_std, marker='^', label='Execution', capsize=3, alpha=0.7)
        ax.errorbar(depths, total_times, yerr=total_std, marker='d', label='Total', capsize=3, alpha=0.9, linewidth=2)
        
        ax.set_xlabel('Circuit Depth', fontsize=12)
        ax.set_ylabel('Time (ms)', fontsize=12)
        ax.set_title(f'{qubits}-Qubit Circuits\nTiming Breakdown', fontsize=14, fontweight='bold')
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved timing breakdown plot: {output_file}")
    plt.close()


def plot_execution_time_only(results_by_qubits, output_file="qiskit_execution_time.png"):
    """
    Create plots showing only execution time for each qubit count
    
    Args:
        results_by_qubits: Dictionary of results organized by qubit count
        output_file: Output filename for the plot
    """
    qubit_counts = sorted(results_by_qubits.keys())
    n_plots = len(qubit_counts)
    
    fig, axes = plt.subplots(1, n_plots, figsize=(7*n_plots, 6))
    if n_plots == 1:
        axes = [axes]
    
    for idx, qubits in enumerate(qubit_counts):
        ax = axes[idx]
        data = results_by_qubits[qubits]
        
        depths = [d['depth'] for d in data]
        execute_times = [d['execute_avg_ms'] for d in data]
        execute_std = [d['execute_std_ms'] for d in data]
        
        ax.errorbar(depths, execute_times, yerr=execute_std, marker='o', 
                   color='#2E86AB', capsize=5, linewidth=2, markersize=8)
        ax.fill_between(depths, 
                        np.array(execute_times) - np.array(execute_std),
                        np.array(execute_times) + np.array(execute_std),
                        alpha=0.2, color='#2E86AB')
        
        ax.set_xlabel('Circuit Depth', fontsize=12)
        ax.set_ylabel('Execution Time (ms)', fontsize=12)
        ax.set_title(f'{qubits}-Qubit Circuits\nExecution Time', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved execution time plot: {output_file}")
    plt.close()


def plot_total_time(results_by_qubits, output_file="qiskit_total_time.png"):
    """
    Create plots showing total time for each qubit count
    
    Args:
        results_by_qubits: Dictionary of results organized by qubit count
        output_file: Output filename for the plot
    """
    qubit_counts = sorted(results_by_qubits.keys())
    n_plots = len(qubit_counts)
    
    fig, axes = plt.subplots(1, n_plots, figsize=(7*n_plots, 6))
    if n_plots == 1:
        axes = [axes]
    
    for idx, qubits in enumerate(qubit_counts):
        ax = axes[idx]
        data = results_by_qubits[qubits]
        
        depths = [d['depth'] for d in data]
        total_times = [d['total_avg_ms'] for d in data]
        total_std = [d['total_std_ms'] for d in data]
        
        ax.errorbar(depths, total_times, yerr=total_std, marker='s', 
                   color='#A23B72', capsize=5, linewidth=2, markersize=8)
        ax.fill_between(depths, 
                        np.array(total_times) - np.array(total_std),
                        np.array(total_times) + np.array(total_std),
                        alpha=0.2, color='#A23B72')
        
        ax.set_xlabel('Circuit Depth', fontsize=12)
        ax.set_ylabel('Total Time (ms)', fontsize=12)
        ax.set_title(f'{qubits}-Qubit Circuits\nTotal Time', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved total time plot: {output_file}")
    plt.close()


def plot_comparison(results_by_qubits, output_file="qiskit_qubit_comparison.png"):
    """
    Create comparison plot showing all qubit counts on same axes
    
    Args:
        results_by_qubits: Dictionary of results organized by qubit count
        output_file: Output filename for the plot
    """
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    colors = plt.cm.viridis(np.linspace(0.2, 0.8, len(results_by_qubits)))
    
    for idx, (qubits, color) in enumerate(zip(sorted(results_by_qubits.keys()), colors)):
        data = results_by_qubits[qubits]
        
        depths = [d['depth'] for d in data]
        execute_times = [d['execute_avg_ms'] for d in data]
        execute_std = [d['execute_std_ms'] for d in data]
        total_times = [d['total_avg_ms'] for d in data]
        total_std = [d['total_std_ms'] for d in data]
        
        # Execution time comparison
        ax1.errorbar(depths, execute_times, yerr=execute_std, 
                    marker='o', label=f'{qubits} qubits', capsize=3, 
                    color=color, linewidth=2)
        
        # Total time comparison
        ax2.errorbar(depths, total_times, yerr=total_std, 
                    marker='s', label=f'{qubits} qubits', capsize=3, 
                    color=color, linewidth=2)
    
    ax1.set_xlabel('Circuit Depth', fontsize=12)
    ax1.set_ylabel('Execution Time (ms)', fontsize=12)
    ax1.set_title('Execution Time Comparison', fontsize=14, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    
    ax2.set_xlabel('Circuit Depth', fontsize=12)
    ax2.set_ylabel('Total Time (ms)', fontsize=12)
    ax2.set_title('Total Time Comparison', fontsize=14, fontweight='bold')
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Saved comparison plot: {output_file}")
    plt.close()


def main():
    """Generate all plots from benchmark results"""
    print("=" * 70)
    print("QISKIT BENCHMARK PLOTTING")
    print("=" * 70)
    
    # Load results
    print("\nLoading benchmark results...")
    try:
        results = load_benchmark_results()
        print(f"✓ Loaded results for {len(results)} qubit configurations")
        for qubits, data in sorted(results.items()):
            print(f"  - {qubits} qubits: {len(data)} depth values")
    except FileNotFoundError as e:
        print(f"Error: {e}")
        print("Please run benchmark_qiskit_random.py first to generate results.")
        return
    
    # Create plots
    print("\nGenerating plots...")
    plot_timing_breakdown(results)
    plot_execution_time_only(results)
    plot_total_time(results)
    plot_comparison(results)
    
    print("\n" + "=" * 70)
    print("All plots generated successfully!")
    print("=" * 70)


if __name__ == "__main__":
    main()
