#!/usr/bin/env python3
"""
Plot TLP benchmark results from JSON file.
Shows only puzzle generation and reveal/solve times (without garbling).
"""

import json
import matplotlib.pyplot as plt


def plot_results_from_json(json_file='tlp_benchmark_results.json', output_file='tlp_generation_solve_plot.png'):
    """Load results from JSON and plot generation + solve times."""
    
    # Load results
    with open(json_file, 'r') as f:
        results = json.load(f)
    
    print(f"Loaded results from {json_file}")
    print(f"Data points: {len(results['T_values'])}")
    
    # Create plot
    plt.figure(figsize=(12, 7))
    
    T_values = results['T_values']
    
    # Plot two lines (excluding garbling)
    plt.plot(T_values, results['generation_times'], 'r-s', 
             label='Puzzle Generation', linewidth=2, markersize=5)
    plt.plot(T_values, results['reveal_times'], 'g-^', 
             label='Reveal/Solve Phase', linewidth=2, markersize=5)
    
    plt.xlabel('T (Time Parameter)', fontsize=12)
    plt.ylabel('Time (seconds)', fontsize=12)
    plt.title('TLP Puzzle Generation & Solving Performance vs T', fontsize=14, fontweight='bold')
    plt.legend(fontsize=11)
    plt.grid(True, alpha=0.3)
    
    # Add minor gridlines
    plt.grid(True, which='minor', alpha=0.1)
    plt.minorticks_on()
    
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight')
    print(f"✓ Plot saved to {output_file}")
    
    # Show the plot
    plt.show()


if __name__ == "__main__":
    plot_results_from_json()
