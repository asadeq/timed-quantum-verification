"""
enhanced_hybrid_hhl.preprocessing
==================================
Utility functions for preparing linear systems for the Enhanced Hybrid HHL
solver:

  - hermitianize_matrix(A, b)   — block-embedding + power-of-2 padding
  - make_preprocessor(...)      — factory for a Yalovetzky preprocessing
                                   callable that works with Qiskit Aer backends
  - solve_hhl(A, b, ...)        — end-to-end: hermitianize → build problem →
                                   run HHL for every component → extract solution

Public API (importable from the package root via enhanced_hybrid_hhl):
    from enhanced_hybrid_hhl.preprocessing import (
        hermitianize_matrix,
        make_preprocessor,
        solve_hhl,
    )
"""

from __future__ import annotations

import time
import numpy as np

__all__ = [
    "hermitianize_matrix",
    "make_preprocessor",
    "solve_hhl",
]


# ---------------------------------------------------------------------------
# Hermitianization
# ---------------------------------------------------------------------------

def hermitianize_matrix(A, b):
    """
    Lift an arbitrary N×N matrix into a Hermitian system suitable for HHL.

    Construction (standard block embedding):
        A_H = [[0,  A ],      b_H = [b]
               [A†, 0 ]]             [0]

    The solution z = A⁻¹b occupies the SECOND half (indices N..2N) of the HHL
    output vector.  If 2N is not a power of 2 the block is padded to the next
    power of 2 (required by QuantumLinearSystemProblem).

    Returns
    -------
    A_H          : np.ndarray  — real Hermitian matrix (dim = next power-of-2 ≥ 2N)
    b_H          : np.ndarray  — extended b vector, shape (dim, 1)
    N_orig       : int         — original system size (needed for result extraction)
    was_hermitian: bool        — True if A was already Hermitian before embedding
    """
    A = np.array(A, dtype=complex)
    b = np.array(b, dtype=complex).flatten()
    N = A.shape[0]

    was_hermitian = np.allclose(A, np.conj(A).T)

    # Block embedding: [[0, A], [A†, 0]]
    A_block = np.zeros((2 * N, 2 * N), dtype=complex)
    A_block[:N, N:] = A
    A_block[N:, :N] = np.conj(A).T

    b_block = np.zeros(2 * N, dtype=complex)
    b_block[:N] = b

    # Pad to next power of 2 if needed
    dim = 2 * N
    next_pow2 = 1
    while next_pow2 < dim:
        next_pow2 *= 2

    if next_pow2 > dim:
        A_pad = np.eye(next_pow2, dtype=complex)
        A_pad[:dim, :dim] = A_block
        b_pad = np.zeros(next_pow2, dtype=complex)
        b_pad[:dim] = b_block
        A_block, b_block = A_pad, b_pad

    return A_block.real, b_block.real.reshape(-1, 1), N, was_hermitian


# ---------------------------------------------------------------------------
# Yalovetzky preprocessor factory
# ---------------------------------------------------------------------------

def make_preprocessor(clock: int, max_eigenvalue: float, backend):
    """
    Return a Yalovetzky preprocessing callable compatible with Qiskit Aer.

    The upstream ``Yalovetzky_preprocessing.estimate()`` has a call-signature
    mismatch when used with a real Aer backend (it calls ``get_result()`` with a
    positional argument it doesn't accept).  This factory subclasses the class
    and overrides ``estimate()`` to fix that, then returns the bound method.

    A *fresh instance* is created on every call so the internal eigenvalue cache
    is isolated per matrix — reusing an instance across different matrices would
    silently return stale eigenvalues.

    Parameters
    ----------
    clock         : number of clock qubits for QPE
    max_eigenvalue: upper bound on |eigenvalue| of the Hermitian matrix
    backend       : Qiskit Aer backend (e.g. AerSimulator())
    """
    from enhanced_hybrid_hhl import Yalovetzky_preprocessing

    class _FixedYalovetzky(Yalovetzky_preprocessing):
        def estimate(self, problem):
            self.problem = problem

            if getattr(problem, "state_preparation", None) is None:
                from qiskit.circuit.library import StatePreparation
                from qiskit.quantum_info import Statevector
                self.state_preparation = StatePreparation(
                    Statevector(problem.b_vector)
                )
            else:
                self.state_preparation = problem.state_preparation

            if getattr(problem, "hamiltonian_simulation", None) is None:
                from qiskit.circuit.library import HamiltonianGate
                if self.max_eigenvalue is None:
                    self.scale = self.find_scale(self.alpha)
                else:
                    self.scale = abs(
                        (0.5 - 2 ** -self.clock) / self.max_eigenvalue
                    )
                    self.hamiltonian_simulation = HamiltonianGate(
                        problem.A_matrix, -2 * np.pi * self.scale
                    )
            else:
                self.hamiltonian_simulation = problem.hamiltonian_simulation

            if hasattr(self, "max_clock"):
                self.adjust_clock()
                self.scale = abs((0.5 - 2 ** -self.clock) / self.max_eigen)

            if not hasattr(self, "result"):
                self.result = self.get_result()

            eigenvalue_list = [
                eig / (self.scale * 2 ** self.clock)
                for eig in self.result.keys()
                if self.result[eig] > self.min_prob
            ]
            eigenbasis_projection_list = [
                self.result[eig]
                for eig in self.result.keys()
                if self.result[eig] > self.min_prob
            ]
            return eigenvalue_list, eigenbasis_projection_list

    return _FixedYalovetzky(
        clock=clock, max_eigenvalue=max_eigenvalue, backend=backend
    ).estimate


# ---------------------------------------------------------------------------
# End-to-end HHL solver
# ---------------------------------------------------------------------------

def solve_hhl(A, b, num_clock_qubits: int = 7, verbose: bool = False):
    """
    Hermitianize A and b, then run the Enhanced Hybrid HHL on a local
    AerSimulator for every output component.

    Returns
    -------
    dict with keys:
        hhl_probs          : np.ndarray  — raw probability vector (all system_dim components)
        solution           : np.ndarray  — extracted HHL solution (N_orig components, normalised)
        classical_solution : np.ndarray  — classical A⁻¹b (normalised, for comparison)
        l2_error           : float
        circuit_depth      : int
        total_time         : float       — seconds
        component_times    : list[float]
        N_orig             : int
        system_dim         : int
        was_hermitian      : bool
    """
    from qiskit_aer import AerSimulator
    from qiskit.quantum_info import Operator
    from enhanced_hybrid_hhl import (
        HHL,
        EnhancedHybridInversion,
        QuantumLinearSystemProblem,
    )

    A = np.array(A, dtype=float)
    b = np.array(b, dtype=float).flatten()

    # --- hermitianize ---
    A_h, b_h, N_orig, was_hermitian = hermitianize_matrix(A, b)
    system_dim = A_h.shape[0]

    if verbose:
        status = "already Hermitian" if was_hermitian else "not Hermitian"
        print(f"  Matrix: {status}, {N_orig}×{N_orig} → {system_dim}×{system_dim} after embedding")

    # --- build problem & classical reference ---
    problem = QuantumLinearSystemProblem(A_matrix=A_h, b_vector=b_h)
    classical_solution = np.linalg.solve(A, b)
    norm = np.linalg.norm(classical_solution)
    normalized_classical = classical_solution / norm if norm > 0 else classical_solution

    # --- preprocessor ---
    backend = AerSimulator()
    max_eigenvalue = float(np.max(np.abs(np.linalg.eigvals(A_h)))) * 1.2
    preprocessing = make_preprocessor(num_clock_qubits, max_eigenvalue, backend)

    # --- run HHL for each component ---
    hhl_probs, hhl_times = [], []
    circuit_depth = None

    for i in range(system_dim):
        proj = np.zeros((system_dim, system_dim))
        proj[i, i] = 1.0
        t0 = time.perf_counter()
        hhl_inst = HHL(
            get_result_function="get_simulator_result",
            preprocessing=preprocessing,
            operator=Operator(proj),
            eigenvalue_inversion=EnhancedHybridInversion,
            backend=backend,
        )
        result = hhl_inst.estimate(
            problem=problem,
            num_clock_qubits=num_clock_qubits,
            max_eigenvalue=max_eigenvalue,
        )
        elapsed = time.perf_counter() - t0
        hhl_times.append(elapsed)
        hhl_probs.append(float(result.results_processed.real))
        if circuit_depth is None:
            circuit_depth = result.circuit_depth
        if verbose:
            print(f"  x[{i}] = {hhl_probs[-1]:.6f}  ({elapsed:.2f}s)")

    hhl_probs = np.array(hhl_probs)

    # Solution is in the SECOND half of the block-embedded output (indices N_orig..2*N_orig)
    hhl_x = hhl_probs[N_orig: 2 * N_orig]
    norm_hhl = np.linalg.norm(hhl_x)
    normalized_hhl = hhl_x / norm_hhl if norm_hhl > 0 else hhl_x
    l2_error = float(np.linalg.norm(normalized_hhl - normalized_classical))

    return {
        "hhl_probs":          hhl_probs,
        "solution":           normalized_hhl,
        "classical_solution": normalized_classical,
        "l2_error":           l2_error,
        "circuit_depth":      circuit_depth,
        "total_time":         sum(hhl_times),
        "component_times":    hhl_times,
        "N_orig":             N_orig,
        "system_dim":         system_dim,
        "was_hermitian":      was_hermitian,
    }
