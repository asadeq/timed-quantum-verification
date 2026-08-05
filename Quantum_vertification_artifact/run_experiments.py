#!/usr/bin/env python3
"""
Quantum Verification Artifact — Run All Experiments
=====================================================
Runs three independent experiments and displays results:

  1. Enhanced Hybrid HHL  — solves a linear system on a local Qiskit simulator,
                             reports accuracy (L2 error vs classical) and timing.

  2. Time-Lock Puzzle (TLP) — benchmarks garbling setup, puzzle generation, and
                               puzzle solving across a range of T values, then
                               plots all three timing curves.

  3. Scaling experiment     — sweeps matrix size N, times HHL on 5 random N×N
                               matrices per size, derives the circuit depth (= T)
                               for each N, runs TLP at that T, and plots HHL time
                               vs TLP solve time side-by-side indexed by N.

Usage:
    python run_experiments.py                 # run all three experiments (default)
    python run_experiments.py --hhl-only      # only Experiment 1
    python run_experiments.py --tlp-only      # only Experiment 2
    python run_experiments.py --scaling-only  # only Experiment 3

All experiment parameters (matrix, T range, N values, …) are configured in
the INPUTS section near the top of this file.
"""

import argparse
import secrets
import time
import json

import os
import numpy as np
import matplotlib.pyplot as plt

# ===========================================================================
# INPUTS — edit this section to configure all experiments
# ===========================================================================

# ---------------------------------------------------------------------------
# Experiment 1: Enhanced Hybrid HHL
# ---------------------------------------------------------------------------
# Linear system  A x = b  to solve.  A can be any square matrix (non-Hermitian
# is fine — it will be block-embedded automatically).
HHL_A = np.array([[2.0, 1.0],
                  [0.0, 1.5]])
HHL_B = np.array([1.0, 2.0])

# ---------------------------------------------------------------------------
# Experiment 2: Time-Lock Puzzle benchmark
# ---------------------------------------------------------------------------
# Range of T values to benchmark and number of timed trials per T.
TLP_T_MIN    = 1
TLP_T_MAX    = 10
TLP_TRIALS   = 2

# ---------------------------------------------------------------------------
# Experiment 3: Scaling experiment
# ---------------------------------------------------------------------------
# Matrix sizes N to sweep.  Each N must appear in N_TO_T below.
SCALING_N_VALUES    = [2, 4, 8]
# Number of random N×N matrices to time per N (more = smoother averages).
SCALING_NUM_MATRICES = 10
# Clock qubits for QPE inside the scaling experiment.
# 6 qubits matches the paper's circuit depths (N=2→~900, N=4→~1900, N=8→~4600).
SCALING_NUM_CLOCK_QUBITS = 7

# Whether to estimate TLP PSolve time via linear projection (True, fast) or
# actually run the full TLP protocol at T=N_TO_T[N] to get a real measurement
# (False, slow — can take a very long time for large T).
SCALING_PROJECT_TLP = True

# Maps matrix size N → the T (μ) value passed to PythonGarbledTLP.
# T controls the time-lock hardness (PSolve evaluates a garbled SHA-256 circuit T times sequentially).
# These values are chosen so that the projected PSolve time just exceeds the
# measured HHL time on this hardware. They are not necessarily portable across machines —
# a faster CPU will need larger T to maintain the same timing relationship.
N_TO_T: dict[int, int] = {
    2:   250,
    4:   800,
    8:   4000,
    16: 13000,
}


# ===========================================================================


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title):
    bar = "=" * 65
    print(f"\n{bar}")
    print(f"  {title}")
    print(bar)


# ---------------------------------------------------------------------------
# Experiment 1 — Enhanced Hybrid HHL
# ---------------------------------------------------------------------------

def run_hhl_experiment(verbose=True):
    """
    Solve the linear system defined by HHL_A and HHL_B (see INPUTS section)
    using the Enhanced Hybrid HHL algorithm on a local Qiskit AerSimulator.
    Returns a result dict and a matplotlib Figure.
    """
    section("EXPERIMENT 1 — Enhanced Hybrid HHL (local simulator)")

    from enhanced_hybrid_hhl.preprocessing import solve_hhl

    A = HHL_A
    b = HHL_B
    N_orig = A.shape[0]

    if verbose:
        print(f"\nInput matrix A ({N_orig}×{N_orig}):")
        print(f"  {A.tolist()}")
        print(f"  b = {b.tolist()}")
        print(f"  Hermitian: {np.allclose(A, np.conj(A).T)}   "
              f"Condition number: {np.linalg.cond(A):.4f}")

    print("\nRunning Enhanced HHL (preprocessing + simulation)…")
    res = solve_hhl(A, b, verbose=verbose)

    print(f"\n{'─'*50}")
    print(f"  Classical solution (normalized): {res['classical_solution']}")
    print(f"  HHL solution      (normalized): {res['solution']}")
    print(f"  L2 error:        {res['l2_error']:.6f}")
    print(f"  Circuit depth:   {res['circuit_depth']}")
    print(f"  Total HHL time:  {res['total_time']:.2f}s")
    print(f"{'─'*50}")

    results = {
        "N_orig":               res["N_orig"],
        "normalized_hhl":       res["solution"].tolist(),
        "normalized_classical": res["classical_solution"].tolist(),
        "l2_error":             res["l2_error"],
        "circuit_depth":        res["circuit_depth"],
        "total_time":           res["total_time"],
        "was_hermitian":        res["was_hermitian"],
    }

    return results


# ---------------------------------------------------------------------------
# Experiment 2 — Time-Lock Puzzle benchmark
# ---------------------------------------------------------------------------

def run_tlp_experiment(T_min=None, T_max=None, trials=None, verbose=True):
    """
    Benchmark TLP garbling setup, puzzle generation, and puzzle solving
    across T_min..T_max.  Inputs default to TLP_T_MIN/TLP_T_MAX/TLP_TRIALS
    from the INPUTS section.  Returns aggregated timing dict and a Figure.
    """
    section("EXPERIMENT 2 — Time-Lock Puzzle (TLP) Benchmark")

    if T_min   is None: T_min   = TLP_T_MIN
    if T_max   is None: T_max   = TLP_T_MAX
    if trials  is None: trials  = TLP_TRIALS

    from timelock_puzzle.tlp_garbling import PythonGarbledTLP

    print(f"\nT range: {T_min} → {T_max}   |   Trials per T: {trials}\n")

    agg = {
        "T_values": [],
        "garbling_times": [],
        "generation_times": [],
        "solve_times": [],
        "verify_times": [],
    }

    for T in range(T_min, T_max + 1):
        print(f"  T={T:3d}", end="  ", flush=True)
        g_times, gen_times, rev_times, ver_times = [], [], [], []

        for _ in range(trials):
            tlp = PythonGarbledTLP(T=T, garbling_mode="prgc")

            # --- garbling setup (one-time cost)
            t0 = time.perf_counter()
            pp = tlp.PSetup_Garble()
            g_times.append(time.perf_counter() - t0)

            # --- puzzle generation
            secret_bit = secrets.randbits(1)
            t0 = time.perf_counter()
            puzzle = tlp.PGen(secret_bit, pp)
            gen_times.append(time.perf_counter() - t0)

            # --- puzzle solving / reveal (also returns y for PVerify)
            t0 = time.perf_counter()
            recovered, y = tlp.PSolve(puzzle, pp)
            rev_times.append(time.perf_counter() - t0)

            # --- verification (constant-time Goldreich-Levin parity check)
            t0 = time.perf_counter()
            accepted = tlp.PVerify(recovered, y, puzzle)
            ver_times.append(time.perf_counter() - t0)
            assert accepted, "PVerify rejected a correctly recovered secret!"

            assert recovered == secret_bit, "TLP correctness failure!"
            print(".", end="", flush=True)

        agg["T_values"].append(T)
        agg["garbling_times"].append(float(np.mean(g_times)))
        agg["generation_times"].append(float(np.mean(gen_times)))
        agg["solve_times"].append(float(np.mean(rev_times)))
        agg["verify_times"].append(float(np.mean(ver_times)))

        print(
            f"  garble={np.mean(g_times):.3f}s  "
            f"gen={np.mean(gen_times):.4f}s  "
            f"solve={np.mean(rev_times):.4f}s  "
            f"verify={np.mean(ver_times):.6f}s"
        )

    print(f"\n{'─'*50}")
    print("  All trials passed correctness check.")
    print(f"{'─'*50}")

    # save JSON
    with open("tlp_benchmark_results6.json", "w") as f:
        json.dump(agg, f, indent=2)
    print("  Results saved → tlp_benchmark_results6.json")

    return agg


# ---------------------------------------------------------------------------
# Experiment 3 — Scaling: HHL time & TLP time vs matrix size N
# ---------------------------------------------------------------------------

def run_scaling_experiment(N_values=None, num_matrices=None, num_clock_qubits=None,
                           max_condition=50, verbose=True, project_tlp=None):
    """
    For each N in N_values:
      1. Generate num_matrices random N×N matrices (ill-conditioned ones skipped).
      2. Hermitianize each, run full Enhanced HHL, record total time + circuit depth.
      3a. project_tlp=True  (default, fast): calibrate PSolve at T=1..5, fit a
          linear model solve_time ≈ slope·T + intercept, then project to
          T = N_TO_T[N].  PSolve time is O(T) so the linear fit extrapolates
          exactly; actually running PSolve at T~250-4000 would take too long.
      3b. project_tlp=False (verify mode):  actually run PSetup_Garble + PGen +
          PSolve at T = N_TO_T[N] for each N to obtain the true measured time.
          Warning: this can take a very long time for large T values.
      4. Return timing data; the caller is responsible for plotting.

    Inputs default to SCALING_N_VALUES / SCALING_NUM_MATRICES / N_TO_T from
    the INPUTS section at the top of this file.

    The key claim: TLP PSolve time at T = N_TO_T[N] exceeds HHL time.
    """
    section("EXPERIMENT 3 — Scaling: Enhanced HHL & TLP vs Matrix Size N")

    from qiskit_aer import AerSimulator
    from qiskit.quantum_info import Operator
    from enhanced_hybrid_hhl import (
        HHL,
        EnhancedHybridInversion,
        QuantumLinearSystemProblem,
    )
    from enhanced_hybrid_hhl.preprocessing import hermitianize_matrix, make_preprocessor
    from timelock_puzzle.tlp_garbling import PythonGarbledTLP

    if N_values      is None: N_values      = SCALING_N_VALUES
    if num_matrices  is None: num_matrices  = SCALING_NUM_MATRICES
    if num_clock_qubits is None: num_clock_qubits = SCALING_NUM_CLOCK_QUBITS
    if project_tlp   is None: project_tlp   = SCALING_PROJECT_TLP

    # Validate all N values have a known T before starting
    unknown = [N for N in N_values if N not in N_TO_T]
    if unknown:
        raise ValueError(
            f"N values {unknown} are not in the N_TO_T lookup table. "
            f"Supported sizes: {sorted(N_TO_T.keys())}"
        )

    backend = AerSimulator()

    # ── TLP timing strategy ──────────────────────────────────────────────
    cal_slope, cal_intercept = None, None

    if project_tlp:
        # Calibrate PSolve at small T, fit linear model, project to N_TO_T[N].
        # Running PSetup_Garble at T~250-1900 would take many minutes; PSolve
        # is O(T) so the linear projection is exact up to noise.
        cal_T_max = 5   # small T values complete in seconds; linear fit extrapolates to large T
        cal_T_vals, cal_solve_times = [], []
        print(f"\n  TLP calibration (T=1..{cal_T_max}, 1 trial each, measuring PSolve)…")
        for cal_T in range(1, cal_T_max + 1):
            tlp_cal = PythonGarbledTLP(T=cal_T)
            pp_cal  = tlp_cal.PSetup_Garble()
            bit = secrets.randbits(1)
            puzzle_cal = tlp_cal.PGen(bit, pp_cal)
            t0 = time.perf_counter()
            rec = tlp_cal.PSolve(puzzle_cal, pp_cal)
            solve_t = time.perf_counter() - t0
            assert rec == bit, f"TLP correctness failure at T={cal_T}"
            cal_T_vals.append(cal_T)
            cal_solve_times.append(solve_t)
            print(f"    T={cal_T}: PSolve = {solve_t*1000:.1f} ms")

        cal_slope, cal_intercept = np.polyfit(cal_T_vals, cal_solve_times, 1)
        print(
            f"  Fit: solve_time ≈ {cal_slope*1000:.2f}·T + {cal_intercept*1000:.2f} ms"
            f"  (R² basis for projection to large T)"
        )
    else:
        print(
            "\n  TLP verify mode (project_tlp=False): will run full PSetup_Garble + "
            "PGen + PSolve at T=N_TO_T[N] for each N.\n"
            "  Warning: this may take a very long time for large T values."
        )

    scaling_data = {
        "N_values": [],
        "system_dims": [],
        "hhl_avg_times": [],
        "hhl_std_times": [],
        "circuit_depths": [],
        "fidelities_avg": [],
        "fidelities_std": [],
        "tlp_T_values": [],
        "tlp_solve_times": [],
        "num_matrices": num_matrices,
        "tlp_projected": project_tlp,
        "matrices": [],   # per-matrix detail records
    }

    for N in N_values:
        print(f"\n  ── N = {N}  (target: {num_matrices} matrices, T={N_TO_T[N]}) ──")
        T_for_N = N_TO_T[N]
        hhl_times_list = []
        depth_list = []
        fidelity_list = []
        matrix_records = []
        system_dim_for_N = None
        solved = 0
        attempts = 0

        while solved < num_matrices and attempts < num_matrices * 30:
            attempts += 1
            # Random N×N matrix; skip ill-conditioned ones
            A_raw = np.random.randn(N, N)
            if N > 1 and np.linalg.cond(A_raw) > max_condition:
                continue
            b_raw = np.random.randn(N)
            norm_b = np.linalg.norm(b_raw)
            if norm_b == 0:
                continue
            b_raw = b_raw / norm_b

            # HHL requires Hermitian input; block-embed A into [[0,A],[A†,0]],
            # which doubles system_dim from N to 2N.
            A_h, b_h, _, _ = hermitianize_matrix(A_raw, b_raw)
            system_dim = A_h.shape[0]
            if system_dim_for_N is None:
                system_dim_for_N = system_dim

            try:
                problem = QuantumLinearSystemProblem(A_matrix=A_h, b_vector=b_h)
            except Exception:
                continue

            # 1.2× safety margin so all eigenvalues fit inside the QPE encoding range
            max_ev = float(np.max(np.abs(np.linalg.eigvals(A_h)))) * 1.2
            # new instance per matrix
            preprocessing = make_preprocessor(num_clock_qubits, max_ev, backend)

            circuit_depth = None
            hhl_probs = []
            t0 = time.perf_counter()
            try:
                for i in range(system_dim):
                    proj = np.zeros((system_dim, system_dim))
                    proj[i, i] = 1.0
                    proj_op = Operator(proj)
                    hhl_inst = HHL(
                        get_result_function="get_simulator_result",
                        preprocessing=preprocessing,
                        operator=proj_op,
                        eigenvalue_inversion=EnhancedHybridInversion,
                        backend=backend,
                    )
                    result = hhl_inst.estimate(
                        problem=problem,
                        num_clock_qubits=num_clock_qubits,
                        max_eigenvalue=max_ev,
                    )
                    if circuit_depth is None:
                        circuit_depth = result.circuit_depth
                    hhl_probs.append(float(result.results_processed.real))
            except Exception as e:
                if verbose:
                    print(f"    [skip] HHL error for N={N}: {e}")
                continue

            elapsed = time.perf_counter() - t0
            hhl_times_list.append(elapsed)
            if circuit_depth is not None:
                depth_list.append(circuit_depth)

            # hermitianize_matrix block-embeds A into [[0,A],[A†,0]], doubling the system
            # size. The solution |x⟩ lives in the second half of the state vector (indices N..2N).
            # HHL returns ⟨i|ρ|i⟩ (probabilities); sqrt recovers amplitude magnitudes.
            # HHL cannot recover the sign of components, so fidelity is sign-agnostic.
            hhl_arr = np.array(hhl_probs)
            hhl_x = hhl_arr[N: 2 * N]
            classical_x = np.linalg.solve(A_raw, b_raw)
            hhl_amplitudes = np.sqrt(np.abs(hhl_x))
            classical_abs  = np.abs(classical_x)
            norm_h = np.linalg.norm(hhl_amplitudes)
            norm_c = np.linalg.norm(classical_abs)
            if norm_h > 0 and norm_c > 0:
                fidelity = float(
                    np.abs(np.dot(hhl_amplitudes / norm_h, classical_abs / norm_c)) ** 2
                )
            else:
                fidelity = 0.0
            fidelity_list.append(fidelity)

            solved += 1
            classical_normalized = (classical_abs / norm_c).tolist() if norm_c > 0 else classical_abs.tolist()
            hhl_normalized = (hhl_amplitudes / norm_h).tolist() if norm_h > 0 else hhl_amplitudes.tolist()
            matrix_records.append({
                "matrix_index":        solved,
                "A":                   A_raw.tolist(),
                "b":                   b_raw.tolist(),
                "classical_solution":  classical_normalized,
                "hhl_solution":        hhl_normalized,
                "circuit_depth":       circuit_depth,
                "hhl_time_s":          round(elapsed, 6),
                "fidelity":            round(fidelity, 6),
            })
            print(f"    matrix {solved}/{num_matrices}: {elapsed:.2f}s  "
                  f"(system_dim={system_dim}, depth={circuit_depth}, fidelity={fidelity:.3f})")

        if not hhl_times_list:
            print(f"  N={N}: no successful HHL runs — skipping.")
            continue

        avg_hhl   = float(np.mean(hhl_times_list))
        std_hhl   = float(np.std(hhl_times_list))
        sim_depth = int(round(np.mean(depth_list))) if depth_list else None
        avg_fid   = float(np.mean(fidelity_list)) if fidelity_list else float("nan")
        std_fid   = float(np.std(fidelity_list))  if fidelity_list else float("nan")
        print(
            f"    → avg HHL: {avg_hhl:.3f}s ± {std_hhl:.3f}s   "
            f"sim depth={sim_depth}   fidelity={avg_fid:.3f}   T={T_for_N}"
        )

        if project_tlp:
            tlp_solve_time = float(cal_slope * T_for_N + cal_intercept)
            tlp_solve_time = max(tlp_solve_time, 0.0)   # clamp negative intercept noise
            print(
                f"    Projected TLP PSolve @ T={T_for_N}: "
                f"{tlp_solve_time:.2f}s  "
                f"(= {cal_slope*1000:.2f}×{T_for_N} + {cal_intercept*1000:.2f} ms)"
            )
        else:
            print(f"    Running TLP @ T={T_for_N} (this may take a while)…", flush=True)
            tlp_actual = PythonGarbledTLP(T=T_for_N)
            pp_actual  = tlp_actual.PSetup_Garble()
            bit_actual = secrets.randbits(1)
            puzzle_actual = tlp_actual.PGen(bit_actual, pp_actual)
            t0 = time.perf_counter()
            rec_actual = tlp_actual.PSolve(puzzle_actual, pp_actual)
            tlp_solve_time = time.perf_counter() - t0
            print(f"    Measured TLP PSolve @ T={T_for_N}: {tlp_solve_time:.4f}s")

        scaling_data["N_values"].append(N)
        scaling_data["system_dims"].append(system_dim_for_N)
        scaling_data["hhl_avg_times"].append(avg_hhl)
        scaling_data["hhl_std_times"].append(std_hhl)
        scaling_data["circuit_depths"].append(sim_depth)
        scaling_data["fidelities_avg"].append(avg_fid)
        scaling_data["fidelities_std"].append(std_fid)
        scaling_data["tlp_T_values"].append(T_for_N)
        scaling_data["tlp_solve_times"].append(tlp_solve_time)
        scaling_data["matrices"].append({
            "N":             N,
            "tlp_T":         T_for_N,
            "tlp_mode":      "projected" if project_tlp else "measured",
            "tlp_solve_time_s": round(tlp_solve_time, 6),
            "runs":          matrix_records,
        })
        if project_tlp:
            scaling_data["tlp_cal_slope_ms_per_T"]  = float(cal_slope  * 1000)
            scaling_data["tlp_cal_intercept_ms"]    = float(cal_intercept * 1000)

    if not scaling_data["N_values"]:
        print("\n  No data collected.")
        return scaling_data

    with open("scaling_results.json", "w") as f:
        json.dump(scaling_data, f, indent=2)
    print("\n  Results saved: scaling_results.json")

    N_vals   = scaling_data["N_values"]
    hhl_t    = np.array(scaling_data["hhl_avg_times"])
    hhl_s    = np.array(scaling_data["hhl_std_times"])
    tlp_sol  = np.array(scaling_data["tlp_solve_times"])
    T_vals   = scaling_data["tlp_T_values"]
    sim_deps = scaling_data["circuit_depths"]
    fid_avg  = scaling_data["fidelities_avg"]

    print(f"\n  {'N':>4}  {'sys_dim':>8}  {'HHL (s)':>10}  {'±':>2}  {'std':>8}  "
          f"{'T':>6}  {'sim_d':>6}  {'fidelity':>9}  {'TLP solve (s)':>14}  {'ratio':>7}")
    print(f"  {'─'*4}  {'─'*8}  {'─'*10}  {'─'*10}  {'─'*6}  {'─'*6}  {'─'*9}  {'─'*14}  {'─'*7}")
    for i, N in enumerate(N_vals):
        ratio = tlp_sol[i] / hhl_t[i] if hhl_t[i] > 0 else float("nan")
        sd = sim_deps[i] if sim_deps[i] is not None else "-"
        fid = f"{fid_avg[i]:.3f}" if not np.isnan(fid_avg[i]) else "-"
        print(f"  {N:>4}  {scaling_data['system_dims'][i]:>8}  {hhl_t[i]:>10.3f}  "
              f"{hhl_s[i]:>10.3f}  {T_vals[i]:>6}  {str(sd):>6}  {fid:>9}  "
              f"{tlp_sol[i]:>14.4f}  {ratio:>7.2f}x")

    return scaling_data


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run Enhanced HHL and/or TLP experiments."
    )
    parser.add_argument("--hhl-only",     action="store_true", help="Run only Experiment 1 (HHL)")
    parser.add_argument("--tlp-only",     action="store_true", help="Run only Experiment 2 (TLP)")
    parser.add_argument("--scaling-only", action="store_true", help="Run only Experiment 3 (scaling)")
    parser.add_argument(
        "--tlp-actual",
        action="store_true",
        help=(
            "Experiment 3: actually run PSetup_Garble + PGen + PSolve at "
            "T=N_TO_T[N] for each N instead of using the linear projection. "
            "Produces verified timing but can take a very long time for large T."
        ),
    )
    args = parser.parse_args()

    # Determine which experiments to run
    run_hhl     = args.hhl_only     or (not args.tlp_only and not args.scaling_only)
    run_tlp     = args.tlp_only     or (not args.hhl_only and not args.scaling_only)
    run_scaling = args.scaling_only or (not args.hhl_only and not args.tlp_only)

    from visualization.visuals_generation import (
        plot_hhl_results,
        plot_tlp_results,
        plot_scaling_results,
        generate_tlp_latex_table,
        generate_tlp_table_image,
    )

    hhl_results, tlp_results, scaling_results = None, None, None

    if run_hhl:
        hhl_results = run_hhl_experiment()
        plot_hhl_results(hhl_results)

    if run_tlp:
        tlp_results = run_tlp_experiment()
        plot_tlp_results(tlp_results)
        generate_tlp_latex_table(tlp_results, amortize_over=20)
        generate_tlp_table_image(tlp_results, amortize_over=20)

    if run_scaling:
        project = False if args.tlp_actual else None   # None → use INPUTS default
        scaling_results = run_scaling_experiment(project_tlp=project)
        if scaling_results["N_values"]:
            plot_scaling_results(scaling_results)

    section("ALL DONE")
    if run_hhl:
        print(f"  HHL L2 error:       {hhl_results['l2_error']:.6f}")
        print(f"  HHL circuit depth:  {hhl_results['circuit_depth']}")
        print(f"  HHL total time:     {hhl_results['total_time']:.2f}s")
    if run_tlp:
        print(f"  TLP T range:        {TLP_T_MIN} → {TLP_T_MAX}")
    if run_scaling:
        print(f"  Scaling N values:   {scaling_results['N_values']}")
        print(f"  Scaling T values:   {scaling_results['tlp_T_values']}")
    print("\n  Output files (visualization/outputs/):")
    if run_hhl:
        print("    hhl_results.png")
    if run_tlp:
        print("    tlp_benchmark_plot.png")
        print("    tlp_benchmark_results.json  (in working dir)")
    if run_scaling:
        print("    scaling_results.png")
        print("    scaling_results.json  (in working dir)")

    # plt.show() blocks in non-interactive shells. Set RUN_EXPERIMENTS_SHOW=1
    # to re-enable the interactive pop-up.
    if os.environ.get("RUN_EXPERIMENTS_SHOW") == "1":
        plt.show()


if __name__ == "__main__":
    main()
