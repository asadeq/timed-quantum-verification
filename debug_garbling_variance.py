#!/usr/bin/env python3
"""
Debug script to identify source of garbling time variance.
Run this to see detailed timing breakdown.
"""

import time
import gc
from timelock_puzzle.tlp_garbling import PythonGarbledTLP

def profile_garbling(T=3, trials=10):
    """Profile garbling with detailed timing breakdown."""
    
    print(f"Profiling garbling for T={T} over {trials} trials")
    print("="*70)
    
    times = {
        'init': [],
        'circuit_build': [],
        'deep_copy': [],
        'flip_circuit': [],
        'total_garbling': []
    }
    
    for trial in range(trials):
        # Force garbage collection for consistent state
        gc.collect()
        
        # Time: TLP initialization
        t0 = time.perf_counter()
        tlp = PythonGarbledTLP(T=T, use_sha256=True)
        t1 = time.perf_counter()
        init_time = t1 - t0
        times['init'].append(init_time)
        
        # Time: Circuit building (done in __init__)
        circuit_build_time = init_time  # Included in init
        times['circuit_build'].append(circuit_build_time)
        
        # Enable debug mode
        tlp._debug_times = {}
        
        # Time: PSetup_Garble (includes deep copy + flip circuit)
        t0 = time.perf_counter()
        pp = tlp.PSetup_Garble()
        t1 = time.perf_counter()
        total_garbling = t1 - t0
        times['total_garbling'].append(total_garbling)
        
        # Extract deep copy time if available
        if hasattr(tlp, '_debug_times') and 'deep_copy' in tlp._debug_times:
            deep_copy_time = tlp._debug_times['deep_copy']
            times['deep_copy'].append(deep_copy_time)
            flip_circuit_time = total_garbling - deep_copy_time
            times['flip_circuit'].append(flip_circuit_time)
        else:
            times['deep_copy'].append(0)
            times['flip_circuit'].append(total_garbling)
        
        # Print trial summary
        print(f"Trial {trial+1:2d}: "
              f"Total={total_garbling*1000:7.2f}ms  "
              f"DeepCopy={times['deep_copy'][-1]*1000:7.2f}ms  "
              f"FlipCircuit={times['flip_circuit'][-1]*1000:7.2f}ms")
        
        # Clean up
        del tlp, pp
        gc.collect()
    
    print("\n" + "="*70)
    print("STATISTICS (all times in milliseconds):")
    print("="*70)
    
    for label, timing_list in times.items():
        if not timing_list:
            continue
        timing_ms = [t * 1000 for t in timing_list]
        avg = sum(timing_ms) / len(timing_ms)
        min_t = min(timing_ms)
        max_t = max(timing_ms)
        std = (sum((t - avg)**2 for t in timing_ms) / len(timing_ms)) ** 0.5
        variance_pct = (std / avg * 100) if avg > 0 else 0
        
        print(f"{label:20s}: "
              f"avg={avg:7.2f}  "
              f"min={min_t:7.2f}  "
              f"max={max_t:7.2f}  "
              f"std={std:7.2f}  "
              f"variance={variance_pct:5.1f}%")
    
    print("\n" + "="*70)
    print("ANALYSIS:")
    print("="*70)
    
    # Check if deep copy is the bottleneck
    if times['deep_copy']:
        dc_variance = (max(times['deep_copy']) - min(times['deep_copy'])) / min(times['deep_copy']) * 100
        fc_variance = (max(times['flip_circuit']) - min(times['flip_circuit'])) / min(times['flip_circuit']) * 100
        
        print(f"Deep copy variance:    {dc_variance:.1f}%")
        print(f"Flip circuit variance: {fc_variance:.1f}%")
        
        if dc_variance > 50:
            print("\n⚠️  DEEP COPY is highly variable!")
            print("    Likely causes:")
            print("    - Python memory allocator fragmentation")
            print("    - Garbage collector interference")
            print("    - CPU thermal throttling")
            print("\n    Recommendations:")
            print("    1. Run sequential benchmark instead of parallel")
            print("    2. Use larger batch sizes to amortize variance")
            print("    3. Disable CPU turbo boost for consistency")
        
        if fc_variance > 50:
            print("\n⚠️  FLIP CIRCUIT is highly variable!")
            print("    This shouldn't happen with optimized RNG.")
            print("    Check if optimization was applied correctly.")


if __name__ == "__main__":
    import sys
    
    T = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    trials = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    
    profile_garbling(T=T, trials=trials)
