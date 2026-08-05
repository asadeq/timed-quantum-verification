#!/usr/bin/env python3
"""
Analyze the relationship between T (μ) and solve times in TLP benchmarks
"""

import json
from pathlib import Path
import statistics

def main():
    # Load TLP results
    results_path = Path('benchmark_results_T1_30')
    data = []

    for T in range(1, 31):
        file_path = results_path / f'tlp_benchmark_T{T}.json'
        if file_path.exists():
            with open(file_path, 'r') as f:
                benchmark = json.load(f)
                data.append({
                    'T': benchmark['config']['T'],
                    'solve_avg_ms': benchmark['timing']['solving']['avg_ms']
                })

    # Print the data
    print('=' * 50)
    print('TLP SOLVE TIME ANALYSIS')
    print('=' * 50)
    print()
    print('T (μ) | Solve Time (ms)')
    print('-' * 30)
    for d in data:
        print(f'{d["T"]:5d} | {d["solve_avg_ms"]:12.2f}')

    # Calculate relationships
    T_values = [d['T'] for d in data]
    solve_times = [d['solve_avg_ms'] for d in data]

    # Linear relationship: solve_time = a * T + b
    n = len(data)
    sum_T = sum(T_values)
    sum_solve = sum(solve_times)
    sum_T_solve = sum(t * s for t, s in zip(T_values, solve_times))
    sum_T_sq = sum(t**2 for t in T_values)

    a = (n * sum_T_solve - sum_T * sum_solve) / (n * sum_T_sq - sum_T**2)
    b = (sum_solve - a * sum_T) / n

    print()
    print('=' * 50)
    print('LINEAR RELATIONSHIP ANALYSIS')
    print('=' * 50)
    print()
    print('Model: solve_time = a * μ + b')
    print(f'  a = {a:.4f} ms/μ')
    print(f'  b = {b:.4f} ms')
    print()

    # Calculate R-squared
    y_mean = statistics.mean(solve_times)
    ss_tot = sum((y - y_mean)**2 for y in solve_times)
    ss_res = sum((solve_times[i] - (a * T_values[i] + b))**2 for i in range(n))
    r_squared = 1 - (ss_res / ss_tot)
    print(f'  R² = {r_squared:.6f}')
    print(f'  Correlation: {"Very Strong" if r_squared > 0.99 else "Strong" if r_squared > 0.95 else "Moderate"}')

    # Check if it's roughly linear by computing ratio
    print()
    print('=' * 50)
    print('SOLVE TIME PER μ ANALYSIS')
    print('=' * 50)
    print()
    ratios = []
    for d in data:
        ratio = d['solve_avg_ms'] / d['T']
        ratios.append(ratio)
    
    print(f'Average: {statistics.mean(ratios):.2f} ms/μ')
    print(f'Std Dev: {statistics.stdev(ratios):.2f} ms/μ')
    print(f'Min:     {min(ratios):.2f} ms/μ')
    print(f'Max:     {max(ratios):.2f} ms/μ')
    print()
    print('Sample values:')
    for d in data[::5]:  # Every 5th value
        ratio = d['solve_avg_ms'] / d['T']
        print(f'  μ={d["T"]:2d}: {ratio:.2f} ms/μ')

    print()
    print('=' * 50)
    print('CONCLUSION')
    print('=' * 50)
    print()
    if r_squared > 0.99:
        print(f'✓ The relationship is highly linear (R² = {r_squared:.6f})')
        print(f'✓ Best fit: solve_time ≈ {a:.2f} * μ + {b:.2f} ms')
    else:
        print(f'The relationship shows linearity (R² = {r_squared:.6f})')
        print(f'Approximate: solve_time ≈ {a:.2f} * μ + {b:.2f} ms')

if __name__ == "__main__":
    main()
