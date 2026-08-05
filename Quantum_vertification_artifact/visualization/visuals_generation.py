"""
Visualization — graph generation for all three experiments.

Each function receives a plain data dict (as returned by the corresponding
experiment function in run_experiments.py) and saves the figure to
visualization/outputs/.

Functions
---------
plot_hhl_results(results)       — Experiment 1: solution comparison + error
plot_tlp_results(agg)           — Experiment 2: TLP phase timing curves
plot_scaling_results(scaling_data)  — Experiment 3: depth, HHL time, TLP comparison
generate_tlp_latex_table(agg)   — Experiment 2: LaTeX table of TLP phase times
generate_tlp_table_image(agg)   — Experiment 2: same data rendered as a PNG
"""

import os
from typing import List

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator

# ---------------------------------------------------------------------------
# Output directory — all figures land here
# ---------------------------------------------------------------------------

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


def _out(filename: str) -> str:
    """Return the full path for an output file."""
    return os.path.join(OUTPUT_DIR, filename)


# ---------------------------------------------------------------------------
# Plot settings — tweak these to adjust the look of all graphs
# ---------------------------------------------------------------------------

FIGURE_DPI = 150
GRID_ALPHA = 0.3
MINOR_GRID_ALPHA = 0.1
LINEWIDTH = 2
MARKERSIZE = 7
ANNOTATION_FONTSIZE = 8
LEGEND_FONTSIZE = 9
AXIS_LABEL_FONTSIZE = 11
TITLE_FONTSIZE = 12
SUPTITLE_FONTSIZE = 13

# Colour palette
COLOR_CLASSICAL   = "steelblue"
COLOR_HHL         = "tomato"
COLOR_ERROR       = "darkorange"
COLOR_GARBLE      = "steelblue"
COLOR_GEN         = "tomato"
COLOR_SOLVE       = "green"
COLOR_DEPTH       = "mediumpurple"
COLOR_TLP_PSSOLVE = "green"
COLOR_SECURITY    = "green"


# ===========================================================================
# Experiment 1 — Enhanced Hybrid HHL
# ===========================================================================

def plot_hhl_results(results: dict) -> plt.Figure:
    """
    Plot classical vs HHL solution components and component-wise error.

    Expected keys in *results*:
        N_orig, normalized_hhl, normalized_classical,
        l2_error, circuit_depth, total_time, was_hermitian
    """
    N_orig               = results["N_orig"]
    normalized_hhl       = np.array(results["normalized_hhl"])
    normalized_classical = np.array(results["normalized_classical"])
    l2_error             = results["l2_error"]
    circuit_depth        = results["circuit_depth"]
    total_time           = results["total_time"]
    was_hermitian        = results["was_hermitian"]

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    prep_note = "(auto-hermitianized)" if not was_hermitian else "(Hermitian input)"
    fig.suptitle(
        f"Enhanced Hybrid HHL — Local Simulator Results {prep_note}",
        fontsize=SUPTITLE_FONTSIZE, fontweight="bold",
    )

    x_idx = np.arange(N_orig)
    w = 0.35
    ax = axes[0]
    bars_c = ax.bar(x_idx - w / 2, normalized_classical, w,
                    label="Classical", color=COLOR_CLASSICAL, alpha=0.85)
    bars_h = ax.bar(x_idx + w / 2, normalized_hhl, w,
                    label="HHL", color=COLOR_HHL, alpha=0.85)
    for bar in list(bars_c) + list(bars_h):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(),
                f"{bar.get_height():.3f}", ha="center", va="bottom",
                fontsize=ANNOTATION_FONTSIZE)
    ax.set_xticks(x_idx)
    ax.set_xticklabels([f"x[{i}]" for i in range(N_orig)])
    ax.set_xlabel("Solution Component")
    ax.set_ylabel("Normalized Amplitude")
    ax.set_title("Classical vs HHL Solution")
    ax.legend()
    ax.grid(True, alpha=GRID_ALPHA, axis="y")

    ax2 = axes[1]
    errors = np.abs(normalized_hhl - normalized_classical)
    ax2.bar(x_idx, errors, color=COLOR_ERROR, alpha=0.8)
    ax2.set_xticks(x_idx)
    ax2.set_xticklabels([f"x[{i}]" for i in range(N_orig)])
    ax2.set_xlabel("Solution Component")
    ax2.set_ylabel("Absolute Error")
    ax2.set_title("Component-wise Error")
    ax2.grid(True, alpha=GRID_ALPHA, axis="y")
    textstr = (
        f"L2 Error: {l2_error:.6f}\n"
        f"Circuit Depth: {circuit_depth}\n"
        f"Total Time: {total_time:.2f}s"
    )
    ax2.text(0.05, 0.95, textstr, transform=ax2.transAxes, fontsize=9,
             verticalalignment="top",
             bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.8))

    plt.tight_layout()
    path = _out("hhl_results.png")
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches="tight")
    print(f"  Plot saved → {path}")
    return fig


# ===========================================================================
# Experiment 2 — Time-Lock Puzzle benchmark
# ===========================================================================

def plot_tlp_results(agg: dict) -> plt.Figure:
    """
    Plot TLP garbling, generation, solving, and verification times vs T.

    Expected keys in *agg*:
        T_values, garbling_times, generation_times, solve_times (or reveal_times),
        verify_times
    """
    T_vals = agg["T_values"]

    # Backwards-compat alias: older JSONs called this reveal_times
    solve_ts = agg.get("solve_times", agg.get("reveal_times"))
    if solve_ts is None:
        raise KeyError("agg must contain 'solve_times' or 'reveal_times'")
    verify_ts = agg.get("verify_times", [0.0] * len(T_vals))

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    fig.suptitle("Time-Lock Puzzle — Benchmark Results",
                 fontsize=SUPTITLE_FONTSIZE + 1, fontweight="bold")

    ax1 = axes[0]
    ax1.plot(T_vals, agg["garbling_times"],  "b-o", label="Garbling Setup",
             linewidth=LINEWIDTH, markersize=5)
    ax1.plot(T_vals, agg["generation_times"], "r-s", label="Puzzle Generation",
             linewidth=LINEWIDTH, markersize=5)
    ax1.plot(T_vals, solve_ts,               "g-^", label="Puzzle Solving",
             linewidth=LINEWIDTH, markersize=5)
    ax1.plot(T_vals, verify_ts,              "m-v", label="Verification (PVerify)",
             linewidth=LINEWIDTH, markersize=5)
    ax1.set_xlabel("T (Time Parameter)")
    ax1.set_ylabel("Time (seconds)")
    ax1.set_title("All Phases vs T")
    ax1.legend()
    ax1.grid(True, alpha=GRID_ALPHA)
    ax1.minorticks_on()
    ax1.grid(True, which="minor", alpha=MINOR_GRID_ALPHA)
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))

    ax2 = axes[1]
    ax2.plot(T_vals, agg["generation_times"], "r-s", label="Puzzle Generation",
             linewidth=LINEWIDTH, markersize=5)
    ax2.plot(T_vals, solve_ts,               "g-^", label="Puzzle Solving",
             linewidth=LINEWIDTH, markersize=5)
    ax2.plot(T_vals, verify_ts,              "m-v", label="Verification (PVerify)",
             linewidth=LINEWIDTH, markersize=5)
    ax2.set_xlabel("T (Time Parameter)")
    ax2.set_ylabel("Time (seconds)")
    ax2.set_title("Generation vs Solving vs Verification")
    ax2.legend()
    ax2.grid(True, alpha=GRID_ALPHA)
    ax2.minorticks_on()
    ax2.grid(True, which="minor", alpha=MINOR_GRID_ALPHA)
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))

    plt.tight_layout()
    path = _out("tlp_benchmark_plot5.png")
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches="tight")
    print(f"  Plot saved → {path}")
    return fig


# ===========================================================================
# Experiment 3 — Scaling
# ===========================================================================

def plot_scaling_results(scaling_data: dict) -> plt.Figure:
    """
    Four-panel plot for the scaling experiment (matching the paper's Figure 4):
      (a) Avg HHL circuit depth vs N
      (b) Avg HHL execution time vs N + TLP μ markers
      (c) Avg fidelity vs N (with std-dev band)
      (d) HHL time vs TLP PSolve time head-to-head

    Expected keys in *scaling_data*:
        N_values, hhl_avg_times, hhl_std_times, circuit_depths,
        fidelities_avg, fidelities_std,
        tlp_T_values, tlp_solve_times, num_matrices, tlp_projected
    """
    N_vals       = scaling_data["N_values"]
    hhl_t        = np.array(scaling_data["hhl_avg_times"])
    hhl_s        = np.array(scaling_data["hhl_std_times"])
    tlp_sol      = np.array(scaling_data["tlp_solve_times"])
    T_vals       = scaling_data["tlp_T_values"]
    sim_deps     = scaling_data["circuit_depths"]
    fid_avg      = np.array(scaling_data.get("fidelities_avg", [float("nan")] * len(N_vals)))
    fid_std      = np.array(scaling_data.get("fidelities_std", [float("nan")] * len(N_vals)))
    num_matrices = scaling_data["num_matrices"]
    project_tlp  = scaling_data["tlp_projected"]

    fig, axes = plt.subplots(1, 3, figsize=(22, 5))
    fig.suptitle(
        "Scaling Experiment: Enhanced HHL Compute Time vs TLP Solve Time",
        fontsize=SUPTITLE_FONTSIZE, fontweight="bold",
    )

    # ── Panel (a): Avg circuit depth vs N ────────────────────────────────
    ax1 = axes[0]
    depths = [d if d is not None else float("nan") for d in sim_deps]
    ax1.plot(N_vals, depths, "-o", linewidth=LINEWIDTH, markersize=MARKERSIZE,
             color="steelblue")
    for n, d in zip(N_vals, depths):
        if not np.isnan(d):
            ax1.annotate(str(int(d)), (n, d), textcoords="offset points",
                         xytext=(0, 8), ha="center",
                         fontsize=ANNOTATION_FONTSIZE, color="steelblue")
    ax1.set_xlabel(r"Matrix Size ($N$)", fontsize=AXIS_LABEL_FONTSIZE)
    ax1.set_ylabel("Circuit Depth", fontsize=AXIS_LABEL_FONTSIZE)
    ax1.set_title("(a) Circuit Depth", fontsize=TITLE_FONTSIZE, fontweight="bold")
    ax1.grid(True, alpha=GRID_ALPHA)
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))

    # ── Panel (b): HHL execution time + TLP μ markers ────────────────────
    ax2 = axes[1]
    ax2.plot(N_vals, hhl_t, "-o", linewidth=LINEWIDTH, markersize=MARKERSIZE,
             color="green", label="HHL avg time")
    ax2.fill_between(N_vals,
                     hhl_t - hhl_s, hhl_t + hhl_s,
                     alpha=0.18, color="green")
    # TLP μ markers 
    ax2.scatter(N_vals, tlp_sol, marker="D", s=80, color="#b5651d", zorder=5,
                label=r"TLP $\mu$")
    for n, t_val, ts in zip(N_vals, T_vals, tlp_sol):
        ax2.annotate(fr"$\mu={t_val:,}$", (n, ts),
                     textcoords="offset points", xytext=(0, 10),
                     ha="center", fontsize=7, color="#b5651d")
    ax2.set_xlabel(r"Matrix Size ($N$)", fontsize=AXIS_LABEL_FONTSIZE)
    ax2.set_ylabel("Time (seconds)", fontsize=AXIS_LABEL_FONTSIZE)
    ax2.set_title("(b) Execution Time", fontsize=TITLE_FONTSIZE, fontweight="bold")
    ax2.legend(fontsize=LEGEND_FONTSIZE)
    ax2.grid(True, alpha=GRID_ALPHA)
    ax2.xaxis.set_major_locator(MaxNLocator(integer=True))

    # ── Panel (c): Fidelity vs N ──────────────────────────────────────────
    ax3 = axes[2]
    valid = ~np.isnan(fid_avg)
    if valid.any():
        N_v   = np.array(N_vals)[valid]
        fa_v  = fid_avg[valid]
        fs_v  = fid_std[valid]
        ax3.plot(N_v, fa_v, "o-", linewidth=LINEWIDTH, markersize=MARKERSIZE,
                 color="darkorange", label="Avg fidelity")
        ax3.fill_between(N_v,
                         np.clip(fa_v - fs_v, 0, 1),
                         np.clip(fa_v + fs_v, 0, 1),
                         alpha=0.18, color="darkorange")
    ax3.set_ylim(0, 1.05)
    ax3.set_xlabel(r"Matrix Size ($N$)", fontsize=AXIS_LABEL_FONTSIZE)
    ax3.set_ylabel("Fidelity", fontsize=AXIS_LABEL_FONTSIZE)
    ax3.set_title("(c) Fidelity", fontsize=TITLE_FONTSIZE, fontweight="bold")
    ax3.legend(fontsize=LEGEND_FONTSIZE)
    ax3.grid(True, alpha=GRID_ALPHA)
    ax3.xaxis.set_major_locator(MaxNLocator(integer=True))

    # ── Panel (d): Head-to-head HHL vs TLP ───────────────────────────────
    # tlp_label     = "TLP PSolve (projected)" if project_tlp else "TLP PSolve (measured)"
    # tlp_mode_note = "linearly projected"     if project_tlp else "measured"

    # ax4 = axes[3]
    # ax4.errorbar(N_vals, hhl_t, yerr=hhl_s, fmt="b-o",
    #              linewidth=LINEWIDTH, markersize=MARKERSIZE,
    #              capsize=5, label="HHL Total Time")
    # ax4.plot(N_vals, tlp_sol, "g-^", linewidth=LINEWIDTH, markersize=MARKERSIZE,
    #          label=tlp_label)
    # N_arr = np.array(N_vals, dtype=float)
    # ax4.fill_between(N_arr, hhl_t, tlp_sol,
    #                  where=(tlp_sol >= hhl_t),
    #                  alpha=0.12, color=COLOR_SECURITY,
    #                  label="TLP > HHL (security region)")
    # ax4.set_xlabel(r"Matrix Size ($N$)", fontsize=AXIS_LABEL_FONTSIZE)
    # ax4.set_ylabel("Time (seconds)", fontsize=AXIS_LABEL_FONTSIZE)
    # ax4.set_title(
    #     f"(d) HHL vs TLP PSolve ({tlp_mode_note})",
    #     fontsize=TITLE_FONTSIZE, fontweight="bold",
    # )
    # ax4.legend(fontsize=LEGEND_FONTSIZE)
    # ax4.grid(True, alpha=GRID_ALPHA)
    # ax4.xaxis.set_major_locator(MaxNLocator(integer=True))

    plt.tight_layout()
    path = _out("scaling_results.png")
    fig.savefig(path, dpi=FIGURE_DPI, bbox_inches="tight")
    print(f"  Plot saved → {path}")
    return fig


# ===========================================================================
# LaTeX table generation
# ===========================================================================

def _format_time_value(seconds: float) -> str:
    """Format a time value (in seconds) into a LaTeX string with units.

    Pick microseconds / milliseconds / seconds depending on magnitude.
    """
    if seconds < 1e-3:
        return f"${seconds * 1e6:.2f}$ $\\mu$s"
    if seconds < 1:
        return f"${seconds * 1e3:.2f}$ ms"
    return f"${seconds:.2f}$ s"


def _format_time_value_with_std(seconds: float, std: float) -> str:
    """Like `_format_time_value` but with $\\pm$ standard deviation."""
    if seconds < 1e-3:
        return f"${seconds * 1e6:.2f} \\pm {std * 1e6:.2f}$ $\\mu$s"
    if seconds < 1:
        return f"${seconds * 1e3:.2f} \\pm {std * 1e3:.2f}$ ms"
    return f"${seconds:.2f} \\pm {std:.2f}$ s"


def generate_tlp_latex_table(
    agg: dict,
    amortize_over: int = 20,
    out_dir: str = None,
) -> str:
    """
    Generate a LaTeX table summarizing TLP benchmark phase times.

    Expected keys in *agg* (as returned by ``run_tlp_experiment``):
        T_values, garbling_times, generation_times, solve_times,
        verify_times.

    Each entry's `*_times` is interpreted as a list of mean times (one per
    T value). The generator also produces a "garbling amortized over
    *amortize_over* puzzles" column to show the per-puzzle cost.

    The .tex file is written to ``visualization/outputs/`` by default and
    the absolute path is printed. Returns the path to the .tex file.
    """
    T_vals        = list(agg["T_values"])
    garble_secs   = list(agg["garbling_times"])
    gen_secs      = list(agg["generation_times"])
    solve_secs    = list(agg.get("solve_times", agg.get("reveal_times")))
    verify_secs   = list(agg.get("verify_times", [0.0] * len(T_vals)))

    if out_dir is None:
        out_dir = OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    lines: List[str] = []
    lines.append("% TLP Results Table")
    lines.append("% Generated automatically from run_experiments.py --tlp-only")
    lines.append("")
    lines.append(r"\begin{table}[htbp]")
    lines.append(r"\centering")
    lines.append(r"\caption{Time-Lock Puzzle (TLP) Performance Results}")
    lines.append(r"\label{tab:tlp_results}")
    lines.append(r"\begin{tabular}{|c|c|c|c|c|c|}")
    lines.append(r"\hline")
    lines.append(
        r"\textbf{$\mu$} & \textbf{PSetup} & \textbf{PGen} & \textbf{PSolve} "
        r"& \textbf{PVerify} & \textbf{PSetup/" + str(amortize_over) + r"} \\"
    )
    lines.append(r"\hline")

    for T, g_s, gen_s, solve_s, ver_s in zip(
        T_vals, garble_secs, gen_secs, solve_secs, verify_secs
    ):
        amortized = g_s / amortize_over
        row = " & ".join([
            f"{int(T)}",
            _format_time_value(g_s),
            _format_time_value(gen_s),
            _format_time_value(solve_s),
            _format_time_value(ver_s),
            _format_time_value(amortized),
        ]) + r" \\"
        lines.append(row)

    lines.append(r"\hline")
    lines.append(r"\end{tabular}")
    lines.append(
        r"\footnotesize{PSetup/" + str(amortize_over)
        + r": PSetup time amortized over "
        + str(amortize_over) + r" puzzles; PVerify: one Goldreich-Levin parity check.}"
    )
    lines.append(r"\end{table}")

    out_path = os.path.join(out_dir, "tlp_results_table.tex")
    with open(out_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  LaTeX table saved → {out_path}")
    return out_path


def generate_tlp_table_image(
    agg: dict,
    amortize_over: int = 20,
    out_dir: str = None,
) -> str:
    """
    Render the TLP benchmark results to a PNG table using matplotlib.

    Same inputs as ``generate_tlp_latex_table``. The PNG is saved to
    ``visualization/outputs/tlp_results_table.png`` by default and the path
    is returned. Useful for embedding the table directly in slides /
    markdown without a LaTeX toolchain.
    """
    T_vals      = list(agg["T_values"])
    garble_secs = list(agg["garbling_times"])
    gen_secs    = list(agg["generation_times"])
    solve_secs  = list(agg.get("solve_times", agg.get("reveal_times")))
    verify_secs = list(agg.get("verify_times", [0.0] * len(T_vals)))

    if out_dir is None:
        out_dir = OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    def fmt(seconds: float) -> str:
        if seconds < 1e-3:
            return f"{seconds * 1e6:.2f} µs"
        if seconds < 1:
            return f"{seconds * 1e3:.2f} ms"
        return f"{seconds:.2f} s"

    header = [
        "μ",
        "PGarble",
        "PGen",
        "PSolve",
        "PVerify",
        f"PGarble/{amortize_over}",
    ]
    rows = []
    for T, g_s, gen_s, solve_s, ver_s in zip(
        T_vals, garble_secs, gen_secs, solve_secs, verify_secs
    ):
        rows.append([
            f"{int(T)}",
            fmt(g_s),
            fmt(gen_s),
            fmt(solve_s),
            fmt(ver_s),
            fmt(g_s / amortize_over),
        ])

    n_rows = len(rows) + 1   # header + data
    n_cols = len(header)
    fig_w = max(8.0, 2.0 * n_cols)
    fig_h = max(1.5, 0.45 * n_rows + 0.9)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")

    table = ax.table(
        cellText=rows,
        colLabels=header,
        loc="center",
        cellLoc="center",
        colLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 1.4)

    for col_idx in range(n_cols):
        cell = table[(0, col_idx)]
        cell.get_text().set_fontweight("bold")
        cell.set_facecolor("#E8EEF7")

    ax.set_title(
        "Time-Lock Puzzle (TLP) Performance Results",
        fontsize=TITLE_FONTSIZE + 1,
        fontweight="bold",
        pad=14,
    )

    out_path = os.path.join(out_dir, "tlp_results_table.png")
    fig.savefig(out_path, dpi=FIGURE_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  Table PNG saved → {out_path}")
    return out_path
