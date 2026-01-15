
import numpy as np
from qiskit.quantum_info import Operator

from enhanced_hybrid_hhl import (HHL, 
                                 Lee_preprocessing,  
                                 Yalovetzky_preprocessing,
                                 ideal_preprocessing,
                                 CanonicalInversion,
                                 QuantumLinearSystemProblem, 
                                 QuantumLinearSystemSolver,
                                 EnhancedHybridInversion)

# For AWS Braket integration
from qiskit_braket_provider import BraketProvider
from qiskit_aer import AerSimulator

# For Qiskit operations
from qiskit import QuantumCircuit, transpile


def hermitianize_matrix(A, b):
    """
    Convert a general matrix A and vector b to a Hermitian system.
    For a system Ax = b, convert to:
    [[0, A], [A†, 0]] @ [y, x] = [b, 0]
    where A† is the conjugate transpose of A.
    
    Returns the Hermitian matrix and modified b vector.
    """
    A = np.array(A, dtype=complex)
    b = np.array(b).flatten()
    
    n = A.shape[0]
    
    # Create the Hermitian matrix [[0, A], [A†, 0]]
    hermitian_A = np.zeros((2*n, 2*n), dtype=complex)
    hermitian_A[:n, n:] = A
    hermitian_A[n:, :n] = A.conj().T
    
    # Create the modified b vector [b, 0]
    hermitian_b = np.zeros(2*n, dtype=complex)
    hermitian_b[:n] = b
    
    return hermitian_A.real, hermitian_b.real.reshape(-1, 1)

# Create a wrapper for CanonicalInversion to match the HHL interface
def CanonicalInversionWrapper(eigenvalue_list, eigenbasis_projection_list, num_clock_qubits, **kwargs):
    """
    Wrapper for CanonicalInversion to make it compatible with HHL interface.
    
    The CanonicalInversion function only needs num_clock_qubits, but HHL expects
    all inversion functions to take eigenvalue_list, eigenbasis_projection_list, 
    and num_clock_qubits as parameters.
    """
    # Ignore the eigenvalue_list and eigenbasis_projection_list, 
    # just pass num_clock_qubits to CanonicalInversion
    return CanonicalInversion(num_clock_qubits)


class FixedYalovetzkyPreprocessing(Yalovetzky_preprocessing):
    """
    Fixed version of Yalovetzky_preprocessing that corrects the bug where
    get_result() is called with a parameter when using backend mode.
    """
    
    def estimate(self, problem):
        """
        Fixed estimate method that calls get_result() without parameters
        when using backend mode.
        """
        self.problem = problem

        # If the state_preparation is not specified in the problem, use the standard StatePreparation
        if getattr(problem, 'state_preparation', None) is None:
            from qiskit.circuit.library import StatePreparation
            from qiskit.quantum_info import Statevector
            self.state_preparation = StatePreparation(Statevector(problem.b_vector))
        else:
            self.state_preparation = problem.state_preparation
        
        # If the hamiltonian simulation is not specified in the problem, use the standard HamiltonianGate
        if getattr(problem, 'hamiltonian_simulation', None) is None:
            from qiskit.circuit.library import HamiltonianGate
            import numpy as np
            
            if self.max_eigenvalue == None:
                self.scale = self.find_scale(self.alpha)
            else:
                self.scale = abs((0.5-2**-self.clock)/self.max_eigenvalue)
                self.hamiltonian_simulation = HamiltonianGate(problem.A_matrix, -2*np.pi*self.scale)
        else:
            self.hamiltonian_simulation = problem.hamiltonian_simulation

        if hasattr(self, "max_clock"):
            self.adjust_clock()
            self.scale = abs((0.5-2**-self.clock)/self.max_eigen)
            
        if not hasattr(self, "result"):
            # FIX: Call get_result() without parameters for backend mode
            self.result = self.get_result()
  
        eigenvalue_list = [eig/(self.scale*2**(self.clock)) for eig in self.result.keys() if self.result[eig] > self.min_prob]
        eigenbasis_projection_list = [self.result[eig] for eig in self.result.keys() if self.result[eig] > self.min_prob]
        return eigenvalue_list, eigenbasis_projection_list
    

def create_projection_operator(index, dimension):
    """
    Create a projection operator |i⟩⟨i| for a given index and dimension.
    
    Parameters:
    - index: The basis state to project onto (0 to dimension-1)
    - dimension: The dimension of the Hilbert space
    
    Returns:
    - Operator: Qiskit Operator representing the projection
    """
    proj_matrix = np.zeros((dimension, dimension))
    proj_matrix[index, index] = 1
    return Operator(proj_matrix)


def solve_linear_system_with_hhl(A_matrix, b_vector, 
                                  preprocessing_type='yalovetzky',
                                  num_clock_qubits=4,
                                  max_eigenvalue=None,
                                  backend=None,
                                  use_enhanced_inversion=True,
                                  verbose=True):
    """
    Solve a linear system Ax = b using HHL algorithm for any matrix size N.
    
    This function:
    1. Automatically determines matrix dimension N
    2. Creates N projection operators dynamically
    3. Runs HHL for each projection to measure each component
    4. Compares results with classical solution
    5. Returns all results and visualizations
    
    Parameters:
    ----------
    A_matrix : np.ndarray
        Coefficient matrix (NxN). Will be hermitianized if not Hermitian.
    b_vector : np.ndarray
        Right-hand side vector (Nx1 or length N)
    preprocessing_type : str
        'yalovetzky', 'lee', or 'ideal' (default: 'yalovetzky')
    num_clock_qubits : int
        Number of clock qubits for HHL (default: 4)
    max_eigenvalue : float
        Maximum eigenvalue estimate. If None, uses largest eigenvalue + 20%
    backend : Backend
        Qiskit backend for execution. If None, uses AerSimulator()
    use_enhanced_inversion : bool
        Use EnhancedHybridInversion if True, else CanonicalInversion (default: True)
    verbose : bool
        Print progress information (default: True)
    
    Returns:
    -------
    dict containing:
        - 'hhl_amplitudes': Measured probability amplitudes from HHL
        - 'classical_solution': Classical solution from np.linalg.solve
        - 'normalized_hhl': Normalized HHL solution
        - 'normalized_classical': Normalized classical solution
        - 'error': L2 error between solutions
        - 'circuit_depth': Circuit depth for the HHL implementation
        - 'A_matrix': Input matrix (possibly hermitianized)
        - 'b_vector': Input vector (possibly extended)
        - 'dimension': System dimension N
    """
    
    # Setup
    if backend is None:
        from qiskit_aer import AerSimulator
        backend = AerSimulator()
    
    # Ensure proper array shapes
    A_matrix = np.array(A_matrix)
    b_vector = np.array(b_vector).flatten().reshape(-1, 1)
    
    N = A_matrix.shape[0]
    
    if verbose:
        print("="*70)
        print(f"SOLVING LINEAR SYSTEM WITH HHL (N={N})")
        print("="*70)
        print(f"Matrix shape: {A_matrix.shape}")
        print(f"Vector shape: {b_vector.shape}")
        print(f"Condition number: {np.linalg.cond(A_matrix):.4f}")
    
    # Check if matrix is Hermitian
    is_hermitian = np.allclose(A_matrix, np.conj(A_matrix.T))
    
    if not is_hermitian:
        if verbose:
            print("Matrix is not Hermitian - hermitianizing...")
        A_h, b_h = hermitianize_matrix(A_matrix, b_vector)
        if verbose:
            print(f"   New system size: {A_h.shape}")
            print(f"   Condition number after hermitianization: {np.linalg.cond(A_h):.4f}")
    else:
        A_h, b_h = A_matrix, b_vector
        if verbose:
            print("Matrix is Hermitian now")
    
    # Estimate maximum eigenvalue if not provided
    if max_eigenvalue is None:
        eigenvalues = np.linalg.eigvals(A_h)
        max_eigenvalue = np.max(np.abs(eigenvalues)) * 1.2  # 20% buffer
        if verbose:
            print(f"Estimated max eigenvalue: {max_eigenvalue:.4f}")
    
    # Create quantum problem
    problem = QuantumLinearSystemProblem(A_matrix=A_h, b_vector=b_h)
    ideal_x_statevector = QuantumLinearSystemSolver(problem=problem).ideal_x_statevector
    
    # Setup preprocessing
    if preprocessing_type.lower() == 'lee':
        l = num_clock_qubits + 2
        preprocessing = Lee_preprocessing(
            num_eval_qubits=l,
            max_eigenvalue=max_eigenvalue,
            backend=backend
        ).estimate
    elif preprocessing_type.lower() == 'yalovetzky':
        preprocessing = FixedYalovetzkyPreprocessing(
            clock=num_clock_qubits,
            max_eigenvalue=max_eigenvalue,
            backend=backend
        ).estimate
    elif preprocessing_type.lower() == 'ideal':
        preprocessing = ideal_preprocessing
    else:
        raise ValueError(f"Unknown preprocessing type: {preprocessing_type}")
    
    # Setup inversion
    if use_enhanced_inversion:
        eigenvalue_inversion = EnhancedHybridInversion
    else:
        eigenvalue_inversion = CanonicalInversionWrapper
    
    # Dimension of quantum system (may be larger if hermitianized)
    system_dim = A_h.shape[0]
    
    if verbose:
        print(f"\nRunning HHL with {system_dim} projection operators...")
        print(f"Preprocessing: {preprocessing_type}")
        print(f"Inversion: {'Enhanced Hybrid' if use_enhanced_inversion else 'Canonical'}")
        print(f"Clock qubits: {num_clock_qubits}")
    
    # Create projection operators and measure each component
    hhl_probabilities = []
    circuit_depth = None
    
    for i in range(system_dim):
        if verbose:
            print(f"  Measuring component {i+1}/{system_dim}...", end='')
        
        # Create projection operator for this component
        proj_op = create_projection_operator(i, system_dim)
        
        # Run HHL with this projection
        hhl_instance = HHL(
            get_result_function='get_simulator_result',
            preprocessing=preprocessing,
            operator=proj_op,
            eigenvalue_inversion=eigenvalue_inversion,
            backend=backend
        )
        
        result = hhl_instance.estimate(
            problem=problem,
            num_clock_qubits=num_clock_qubits,
            max_eigenvalue=max_eigenvalue
        )
        
        prob = result.results_processed.real
        hhl_probabilities.append(prob)
        
        if circuit_depth is None:
            circuit_depth = result.circuit_depth
        
        if verbose:
            print(f" P(|{i}⟩) = {prob:.6f}")
    
    hhl_probabilities = np.array(hhl_probabilities)
    
    # Get classical solution
    classical_solution = np.linalg.solve(A_h, b_h).flatten()
    
    # Normalize solutions
    normalized_classical = classical_solution / np.linalg.norm(classical_solution)
    normalized_hhl = hhl_probabilities / np.linalg.norm(hhl_probabilities)
    
    # Calculate error
    error = np.linalg.norm(normalized_hhl - normalized_classical)
    
    if verbose:
        print(f"\n{'='*70}")
        print("RESULTS SUMMARY")
        print(f"{'='*70}")
        print(f"Classical solution: {classical_solution}")
        print(f"HHL probabilities:  {hhl_probabilities}")
        print(f"Normalized classical: {normalized_classical}")
        print(f"Normalized HHL:       {normalized_hhl}")
        print(f"L2 Error: {error:.6f}")
        print(f"Circuit Depth: {circuit_depth}")
        print(f"{'='*70}")
    
    return {
        'hhl_amplitudes': hhl_probabilities,
        'classical_solution': classical_solution,
        'normalized_hhl': normalized_hhl,
        'normalized_classical': normalized_classical,
        'error': error,
        'circuit_depth': circuit_depth,
        'A_matrix': A_h,
        'b_vector': b_h,
        'dimension': system_dim,
        'original_dimension': N,
        'ideal_statevector': ideal_x_statevector
    }


def visualize_hhl_results(results, show_plot=True):
    """
    Visualize the comparison between HHL and classical solutions.
    
    Parameters:
    - results: Dictionary returned by solve_linear_system_with_hhl
    - show_plot: Whether to display the plot (default: True)
    """
    import matplotlib.pyplot as plt
    
    classical_norm = results['normalized_classical']
    hhl_norm = results['normalized_hhl']
    N = len(classical_norm)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    
    # Plot 1: Normalized solutions comparison
    x = np.arange(N)
    width = 0.35
    
    bars1 = ax1.bar(x - width/2, classical_norm, width, 
                    label='Classical (normalized)', alpha=0.8, color='blue')
    bars2 = ax1.bar(x + width/2, hhl_norm, width,
                    label='HHL (normalized)', alpha=0.8, color='red')
    
    ax1.set_xlabel('Solution Component', fontsize=11)
    ax1.set_ylabel('Normalized Amplitude', fontsize=11)
    ax1.set_title(f'Solution Comparison (N={results["original_dimension"]})', fontsize=12, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels([f'x[{i}]' for i in range(N)])
    ax1.legend()
    ax1.grid(True, alpha=0.3, axis='y')
    
    # Add value labels
    for bar in bars1:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.3f}', ha='center', va='bottom', fontsize=8)
    
    for bar in bars2:
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height,
                f'{height:.3f}', ha='center', va='bottom', fontsize=8)
    
    # Plot 2: Error visualization
    errors = np.abs(hhl_norm - classical_norm)
    bars3 = ax2.bar(x, errors, color='orange', alpha=0.7)
    
    ax2.set_xlabel('Solution Component', fontsize=11)
    ax2.set_ylabel('Absolute Error', fontsize=11)
    ax2.set_title('Component-wise Error', fontsize=12, fontweight='bold')
    ax2.set_xticks(x)
    ax2.set_xticklabels([f'x[{i}]' for i in range(N)])
    ax2.grid(True, alpha=0.3, axis='y')
    
    # Add error statistics box
    total_error = results['error']
    max_error = np.max(errors)
    mean_error = np.mean(errors)
    
    textstr = f'Total L2 Error: {total_error:.6f}\\nMax Error: {max_error:.6f}\\nMean Error: {mean_error:.6f}\\nCircuit Depth: {results["circuit_depth"]}'
    props = dict(boxstyle='round', facecolor='lightblue', alpha=0.8)
    ax2.text(0.05, 0.95, textstr, transform=ax2.transAxes, fontsize=9,
            verticalalignment='top', bbox=props)
    
    plt.tight_layout()
    
    if show_plot:
        plt.show()
    
    return fig

if __name__ == "__main__":
    # Example 1: 2x2 Hermitian system
    A_2x2 = np.array([[1.5, 0.5], 
                    [0.5, 1.5]])
    b_2x2 = np.array([[1.], [0.]])

    simulator = AerSimulator()


    results_2x2 = solve_linear_system_with_hhl(
        A_2x2, b_2x2,
        preprocessing_type='yalovetzky',
        num_clock_qubits=4,
        max_eigenvalue=3,
        backend=simulator,  # This uses the Qiskit AerSimulator from cell 1
        use_enhanced_inversion=True,
        verbose=True
    )

    visualize_hhl_results(results_2x2)