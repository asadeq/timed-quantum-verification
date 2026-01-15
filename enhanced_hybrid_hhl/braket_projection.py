"""
AWS Braket Projection Measurement Utilities

Functions for submitting and retrieving projection-based HHL measurements on AWS Braket.
"""

import datetime
import os
import json
import numpy as np
from typing import Dict, List, Tuple, Optional, Union

from qiskit import transpile, QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit.quantum_info import Operator
from qiskit_braket_provider import BraketProvider
import boto3

from .quantum_linear_system import QuantumLinearSystemProblem, QuantumLinearSystemSolver, HHL_Result
from . import ideal_preprocessing, list_preprocessing, EnhancedHybridInversion, HHL


def create_computational_basis_projectors(num_qubits: int, indices: Optional[List[int]] = None) -> List[Tuple[int, Operator]]:
    """
    Create computational basis projection operators.
    
    Args:
        num_qubits: Number of qubits in the solution register
        indices: List of basis state indices to project onto (None = all)
        
    Returns:
        List of (index, projector) tuples
    """
    dimension = 2**num_qubits
    
    if indices is None:
        indices = list(range(dimension))
    
    projectors = []
    for idx in indices:
        # Create |i⟩⟨i| projector
        proj_matrix = np.zeros((dimension, dimension), dtype=complex)
        proj_matrix[idx, idx] = 1.0
        projectors.append((idx, Operator(proj_matrix)))
    
    return projectors


def ensure_all_qubits_measured(circuit: QuantumCircuit) -> QuantumCircuit:
    """Ensure all qubits are measured for AWS Braket compatibility."""
    num_qubits = circuit.num_qubits
    
    measured_qubits = set()
    measured_mapping = {}
    
    for instr in circuit.data:
        if instr.operation.name == 'measure':
            qubit_idx = circuit.qubits.index(instr.qubits[0])
            clbit_idx = circuit.clbits.index(instr.clbits[0])
            measured_qubits.add(qubit_idx)
            measured_mapping[qubit_idx] = clbit_idx
    
    unmeasured = sorted([i for i in range(num_qubits) if i not in measured_qubits])
    
    if not unmeasured:
        return circuit
    
    if circuit.num_clbits < num_qubits:
        additional_bits = num_qubits - circuit.num_clbits
        aux_creg = ClassicalRegister(additional_bits, f'braket_aux')
        circuit.add_register(aux_creg)
    
    used_clbits = set(measured_mapping.values())
    
    for qubit_idx in unmeasured:
        for clbit_idx in range(circuit.num_clbits):
            if clbit_idx not in used_clbits:
                circuit.measure(qubit_idx, clbit_idx)
                used_clbits.add(clbit_idx)
                break
    
    # Verify
    measured_qubits_final = set()
    for instr in circuit.data:
        if instr.operation.name == 'measure':
            measured_qubits_final.add(circuit.qubits.index(instr.qubits[0]))
    
    if len(measured_qubits_final) != num_qubits:
        raise ValueError(
            f"AWS Braket validation failed: Only {len(measured_qubits_final)} out of "
            f"{num_qubits} qubits are measured."
        )
    
    return circuit


def run_braket_projection_submission(
    problem_list: List[QuantumLinearSystemProblem],
    output_dir: str,
    aws_region: str = "eu-west-2",
    device_arn: str = "SV1",
    k_qubits: int = 10,
    shots: int = 3000,
    preprocessing_mode: str = "ideal",
    projection_mode: str = "all_components",
    projection_subset: Optional[List[int]] = None,
    probability_threshold: float = 0,
    max_eigenvalue: float = 10,
    s3_bucket: Optional[str] = None,
    s3_prefix: str = "hhl-projection-results",
    optimization_level: int = 1
) -> str:
    """
    Submit projection-based HHL measurements to AWS Braket.
    
    Args:
        problem_list: List of QuantumLinearSystemProblem instances
        output_dir: Directory to save results JSON file
        aws_region: AWS region (default: "eu-west-2")
        device_arn: Braket device ARN or shorthand like "SV1" (default: "SV1")
        k_qubits: Number of clock qubits (default: 10)
        shots: Number of shots per projection measurement (default: 3000)
        preprocessing_mode: "ideal", "yalovetzky", "lee", or "iterative" (default: "ideal")
        projection_mode: "all_components", "subset", or "custom" (default: "all_components")
        projection_subset: List of component indices for subset mode
        probability_threshold: Probability threshold for eigenvalue filtering (default: 0)
        max_eigenvalue: Maximum eigenvalue for scaling (default: 10)
        s3_bucket: Optional S3 bucket for results
        s3_prefix: S3 prefix for results (default: "hhl-projection-results")
        optimization_level: Transpilation optimization level (default: 1)
        
    Returns:
        Path to the saved results JSON file
    """
    # Setup AWS Braket backend
    boto_session = boto3.Session(region_name=aws_region)
    provider = BraketProvider()
    backend = provider.get_backend(device_arn)
    
    if s3_bucket:
        backend.set_options(s3_destination_folder=(s3_bucket, s3_prefix))
    
    print(f" AWS Braket Backend: {device_arn}")
    print(f"  Region: {aws_region}")
    print(f"  Problems: {len(problem_list)}")
    
    # Determine number of solution qubits
    num_solution_qubits = int(np.log2(len(problem_list[0].b_vector)))
    print(f"  Solution size: {len(problem_list[0].b_vector)} ({num_solution_qubits} qubits)")
    
    # Get projectors based on mode
    if projection_mode == "all_components":
        projectors = create_computational_basis_projectors(num_solution_qubits)
        print(f"  Projection mode: Measuring all {2**num_solution_qubits} components")
    elif projection_mode == "subset":
        if projection_subset is None:
            projection_subset = list(range(2**num_solution_qubits // 2))
        projectors = create_computational_basis_projectors(num_solution_qubits, indices=projection_subset)
        print(f"  Projection mode: Measuring subset {projection_subset}")
    else:
        raise ValueError(f"Unknown projection mode: {projection_mode}")
    
    # Storage for results
    used_problem_list = []
    ideal_preprocessing_list = []
    enhanced_projection_results = []
    
    print(f"\n--- Processing {len(problem_list)} problems ---\n")
    
    for i, problem in enumerate(problem_list):
        print(f"[{i+1}/{len(problem_list)}] Problem {i+1}")
        
        # Store problem
        used_problem_list.append({
            'A_matrix': problem.A_matrix.tolist(),
            'b_vector': problem.b_vector.tolist()
        })
        
        # Compute ideal preprocessing
        solution = QuantumLinearSystemSolver(problem)
        ideal_x = solution.ideal_x_statevector
        ideal_preprocessing_list.append(ideal_preprocessing(problem))
        
        # Select preprocessing method
        if preprocessing_mode == "yalovetzky":
            print("  Using Yalovetzky preprocessing (QCL-QPE quantum-based)")
            from .eigenvalue_preprocessing import Yalovetzky_preprocessing
            y_preprocessing = Yalovetzky_preprocessing(
                clock=k_qubits,
                backend=backend,
                max_eigenvalue=max_eigenvalue,
                min_prob=2**(-k_qubits)
            )
            eigenvalue_list, eigenbasis_projection_list = y_preprocessing.estimate(problem)
            e_preprocessing = list_preprocessing(eigenvalue_list, eigenbasis_projection_list)
        elif preprocessing_mode == "lee":
            print("  Using Lee preprocessing (standard QPE quantum-based)")
            from .eigenvalue_preprocessing import Lee_preprocessing
            
            # Create custom get_result function that ensures all qubits are measured
            def get_braket_lee_result(circ):
                # Ensure all qubits are measured for Braket
                circ = ensure_all_qubits_measured(circ)
                circ.global_phase = 0
                
                transp = transpile(circ, backend, optimization_level=optimization_level)
                transp.global_phase = 0
                transp = ensure_all_qubits_measured(transp)
                
                result = backend.run(transp, shots=shots).result()
                counts = result.get_counts()
                tot = sum(counts.values())
                
                # Extract only the evaluation qubits
                # Lee's construct_circuit measures qubits in reversed order, so:
                # Classical bit 0 has the LSB, classical bit (k_qubits-1) has the MSB
                # But we need to reverse them back to get the proper phase value
                result_dict = {}
                for bitstring, count in counts.items():
                    # Remove spaces
                    bits = bitstring.replace(' ', '')
                    # First k_qubits classical bits contain the phase estimation
                    eval_bits = bits[:k_qubits]
                    
                    # Reverse to get proper bit order (MSB to LSB)
                    eval_bits_reversed = eval_bits[::-1]
                    
                    # Convert to integer with two's complement
                    eval_int = int(eval_bits_reversed, 2)
                    if eval_bits_reversed[0] == '1':  # negative in two's complement
                        eval_int = eval_int - (2**k_qubits)
                    
                    if eval_int in result_dict:
                        result_dict[eval_int] += count / tot
                    else:
                        result_dict[eval_int] = count / tot
                
                return result_dict
            
            lee_preprocessing = Lee_preprocessing(
                num_eval_qubits=k_qubits,
                max_eigenvalue=max_eigenvalue,
                get_result_function=get_braket_lee_result
            )
            eigenvalue_list, eigenbasis_projection_list = lee_preprocessing.estimate(problem)
            e_preprocessing = list_preprocessing(eigenvalue_list, eigenbasis_projection_list)
        elif preprocessing_mode == "iterative":
            print("  Using Iterative QPE preprocessing (quantum-based)")
            from .eigenvalue_preprocessing import Iterative_QPE_Preprocessing
            iter_preprocessing = Iterative_QPE_Preprocessing(
                clock=k_qubits,
                backend=backend,
                max_eigenvalue=max_eigenvalue,
                min_prob=2**(-k_qubits)
            )
            eigenvalue_list, eigenbasis_projection_list = iter_preprocessing.estimate(problem)
            e_preprocessing = list_preprocessing(eigenvalue_list, eigenbasis_projection_list)
        else:
            print("  Using ideal preprocessing (classical)")
            e_preprocessing = ideal_preprocessing
        
        # Create HHL instance
        Enhanced_H_HHL = HHL(
            preprocessing=e_preprocessing,
            eigenvalue_inversion=EnhancedHybridInversion
        )
        
        # Custom get_result function for projection measurements
        def get_braket_projection_result(circuit: QuantumCircuit, prob: QuantumLinearSystemProblem) -> HHL_Result:
            num_sol_qubits = int(np.log2(len(prob.b_vector)))
            solution_qubit_start = circuit.num_qubits - num_sol_qubits
            projection_tasks = []
            
            print(f"  → Submitting {len(projectors)} projection measurements...")
            
            for proj_idx, (basis_state, projector) in enumerate(projectors):
                proj_circuit = circuit.copy()
                
                # Add measurements for solution qubits
                solution_creg = ClassicalRegister(num_sol_qubits, f'sol_meas')
                proj_circuit.add_register(solution_creg)
                
                for j in range(num_sol_qubits):
                    proj_circuit.measure(solution_qubit_start + j, solution_creg[j])
                
                # Ensure all qubits measured
                proj_circuit = ensure_all_qubits_measured(proj_circuit)
                proj_circuit.global_phase = 0
                
                # Transpile
                transpiled_circuit = transpile(proj_circuit, backend=backend, optimization_level=optimization_level)
                transpiled_circuit.global_phase = 0
                transpiled_circuit = ensure_all_qubits_measured(transpiled_circuit)
                
                # Submit to AWS Braket
                try:
                    job = backend.run(transpiled_circuit, shots=shots)
                    task_id = job.job_id()
                    
                    projection_tasks.append({
                        'basis_state': int(basis_state),
                        'task_id': task_id,
                        'shots': shots,
                        'projector_index': proj_idx
                    })
                    
                    print(f"    [{proj_idx+1}/{len(projectors)}] Basis |{basis_state}⟩: {task_id}")
                    
                except Exception as e:
                    print(f"    ✗ Projection {proj_idx} failed: {e}")
                    projection_tasks.append({
                        'basis_state': int(basis_state),
                        'task_id': None,
                        'error': str(e),
                        'projector_index': proj_idx
                    })
            
            # Create result object
            result = HHL_Result()
            result.circuit_results = projection_tasks
            result.task_id = projection_tasks[0]['task_id'] if projection_tasks else None
            result.depth = transpiled_circuit.depth() if 'transpiled_circuit' in locals() else None
            result.circuit_depth = result.depth
            result.num_solution_qubits = num_sol_qubits
            result.projection_mode = True
            
            return result
        
        # Run HHL with projection measurements
        enhanced_result = Enhanced_H_HHL.estimate(
            problem=problem,
            num_clock_qubits=k_qubits,
            max_eigenvalue=max_eigenvalue,
            quantum_conditional_logic=False,
            probability_threshold=probability_threshold,
            get_result_function=get_braket_projection_result
        )
        
        # Store results
        ideal_solution_serializable = [
            {'real': float(x.real), 'imag': float(x.imag)} 
            for x in ideal_x.data
        ]
        
        enhanced_projection_results.append({
            'problem_index': i,
            'projection_tasks': enhanced_result.circuit_results,
            'depth': enhanced_result.depth,
            'num_projections': len(projectors),
            'ideal_solution': ideal_solution_serializable
        })
        
        print(f"  Circuit depth: {enhanced_result.depth}")
        print(f"  Submitted {len(projectors)} measurements\n")
    
    # Save results
    data = {
        'problem_list': used_problem_list,
        'shots': shots,
        'backend': device_arn.lower(),
        'device_arn': device_arn,
        'aws_region': aws_region,
        'ideal_preprocessing_list': ideal_preprocessing_list,
        'probability_threshold': probability_threshold,
        'k_qubits': k_qubits,
        'preprocessing_mode': preprocessing_mode,
        'projection_mode': projection_mode,
        'projection_subset': projection_subset if projection_mode == "subset" else None,
        'num_solution_qubits': num_solution_qubits,
        'num_projections': len(projectors),
        'projector_basis_states': [p[0] for p in projectors],
        'enhanced_projection_results': enhanced_projection_results,
    }
    
    # Generate filename
    current_datetime = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f'braket_projection_N{len(problem_list[0].b_vector)}_hhl_{current_datetime}.json'
    file_path = os.path.join(output_dir, file_name)
    
    with open(file_path, "w") as json_file:
        json.dump(data, json_file, indent=2)
    
    print(f" Results saved to: {file_name}")
    print(f"  Total tasks submitted: {len(problem_list) * len(projectors)}")
    
    return file_path


def run_braket_projection_retrieval(
    result_file_path: str,
    aws_region: str = "eu-west-2",
    device_arn: str = "SV1",
    output_suffix: str = "_retrieval"
) -> str:
    """
    Retrieve and analyze projection measurement results from AWS Braket.
    
    Args:
        result_file_path: Path to the JSON file with submission results
        aws_region: AWS region (default: "eu-west-2")
        device_arn: Braket device ARN or shorthand like "SV1" (default: "SV1")
        output_suffix: Suffix to add to output filename (default: "_retrieval")
        
    Returns:
        Path to the saved retrieval results JSON file
    """
    import boto3
    
    print(f"Loading projection results from: {os.path.basename(result_file_path)}")
    
    with open(result_file_path, 'r') as file:
        data = json.load(file)
    
    # Setup AWS Braket backend
    boto_session = boto3.Session(region_name=aws_region)
    provider = BraketProvider()
    backend = provider.get_backend(device_arn)
    
    print(f" Using AWS Braket Backend: {device_arn}")
    print(f"  Region: {aws_region}\n")
    
    num_solution_qubits = data['num_solution_qubits']
    enhanced_projection_results = data['enhanced_projection_results']
    
    updated_results = []
    
    print(f"--- Retrieving Results from AWS Braket ---\n")
    
    for prob_idx, prob_result in enumerate(enhanced_projection_results):
        print(f"Problem {prob_idx + 1}/{len(enhanced_projection_results)}")
        
        projection_tasks = prob_result['projection_tasks']
        
        # Convert ideal solution from JSON format
        ideal_solution_json = prob_result['ideal_solution']
        if isinstance(ideal_solution_json[0], dict):
            ideal_solution = np.array([
                complex(item['real'], item['imag']) 
                for item in ideal_solution_json
            ])
        else:
            ideal_solution = np.array(ideal_solution_json)
        
        print(f"  Retrieving {len(projection_tasks)} projection measurements...")
        
        # Retrieve each projection task
        retrieved_tasks = []
        all_created_times = []
        all_ended_times = []
        for task in projection_tasks:
            task_id = task.get('task_id')
            basis_state = task.get('basis_state')
            
            if task_id is None:
                print(f"    Basis |{basis_state}⟩: No task ID (submission failed)")
                retrieved_tasks.append(task)
                continue
            
            try:
                job = backend.retrieve_job(task_id)
                status = job.status()
                status_str = str(status.name) if hasattr(status, 'name') else str(status)
                
                # Get timing metadata using boto3 Braket client
                created_at = None
                ended_at = None
                execution_time_seconds = None
                
                try:
                    # Extract region from backend or use default
                    region = backend._aws_session.region_name if hasattr(backend, '_aws_session') else aws_region
                    braket_client = boto3.client('braket', region_name=region)
                    
                    # Get job details from AWS Braket
                    response = braket_client.get_quantum_task(quantumTaskArn=task_id)
                    created_at_raw = response.get('createdAt')
                    ended_at_raw = response.get('endedAt')
                    
                    # Convert to string for JSON serialization
                    created_at = str(created_at_raw) if created_at_raw else None
                    ended_at = str(ended_at_raw) if ended_at_raw else None
                    
                    # Calculate execution time if both timestamps are available
                    if created_at_raw and ended_at_raw:
                        # Parse ISO format timestamps
                        from dateutil import parser
                        created_dt = parser.isoparse(str(created_at_raw))
                        ended_dt = parser.isoparse(str(ended_at_raw))
                        execution_time_seconds = (ended_dt - created_dt).total_seconds()
                except Exception:
                    # If timing retrieval fails, just skip it
                    pass
                
                task_result = {
                    'basis_state': basis_state,
                    'task_id': task_id,
                    'status': status_str,
                    'shots': task['shots'],
                    'created_at': created_at,
                    'ended_at': ended_at,
                    'execution_time_seconds': execution_time_seconds
                }
                
                # Track timing for problem-level statistics
                if created_at:
                    all_created_times.append(created_at)
                if ended_at:
                    all_ended_times.append(ended_at)
                
                if status_str in ['COMPLETED', 'DONE', 'JobStatus.COMPLETED']:
                    result = job.result()
                    counts = result.get_counts()
                    task_result['counts'] = counts
                    
                    # Extract probability
                    debug = (len(retrieved_tasks) == 0)
                    prob, success_rate = extract_solution_probability_from_counts(
                        counts, basis_state, num_solution_qubits, debug=debug
                    )
                    task_result['component_probability'] = float(prob)
                    task_result['success_rate'] = float(success_rate)
                    
                    time_str = f", Time={execution_time_seconds:.1f}s" if execution_time_seconds else ""
                    print(f"    Basis |{basis_state}⟩: P={prob:.4f}, Success={success_rate:.4f}{time_str}")
                else:
                    print(f"    Basis |{basis_state}⟩: Status={status_str}")
                
                retrieved_tasks.append(task_result)
                
            except Exception as e:
                print(f"    Basis |{basis_state}⟩: Retrieval failed - {e}")
                task['error'] = str(e)
                retrieved_tasks.append(task)
        
        # Reconstruct solution vector
        solution_probs, metadata = reconstruct_solution_vector(retrieved_tasks, num_solution_qubits)
        
        # Calculate fidelity
        fidelity = calculate_fidelity(solution_probs, ideal_solution)
        
        # Calculate total problem time
        total_problem_time = None
        first_created_at = None
        last_ended_at = None
        if all_created_times and all_ended_times:
            try:
                from dateutil import parser
                # Parse all timestamps
                created_datetimes = [parser.isoparse(str(t)) for t in all_created_times]
                ended_datetimes = [parser.isoparse(str(t)) for t in all_ended_times]
                
                # Find first creation and last completion
                first_created = min(created_datetimes)
                last_ended = max(ended_datetimes)
                
                # Calculate total time
                total_problem_time = (last_ended - first_created).total_seconds()
                first_created_at = str(all_created_times[created_datetimes.index(first_created)])
                last_ended_at = str(all_ended_times[ended_datetimes.index(last_ended)])
            except Exception:
                pass
        
        print(f"\n  Reconstructed: {solution_probs}")
        print(f"  Ideal probs: {np.abs(ideal_solution)**2 / np.sum(np.abs(ideal_solution)**2)}")
        print(f"  Fidelity: {fidelity:.4f}")
        print(f"  Avg success rate: {metadata['average_success_rate']:.4f}")
        if total_problem_time:
            print(f"  Total problem time: {total_problem_time:.1f}s (first created → last ended)")
        print()
        
        # Update result
        result_data = {
            **prob_result,
            'projection_tasks': retrieved_tasks,
            'reconstructed_solution_probabilities': solution_probs.tolist(),
            'fidelity': float(fidelity),
            'metadata': metadata
        }
        
        # Add problem-level timing if available
        if total_problem_time is not None:
            result_data['total_problem_time_seconds'] = total_problem_time
            result_data['first_created_at'] = first_created_at
            result_data['last_ended_at'] = last_ended_at
        
        updated_results.append(result_data)
    data['enhanced_projection_results'] = updated_results
    
    # Save updated results
    output_dir = os.path.dirname(result_file_path)
    base_name = os.path.basename(result_file_path)
    output_file = base_name.replace('.json', f'{output_suffix}.json')
    output_path = os.path.join(output_dir, output_file)
    
    with open(output_path, 'w') as file:
        json.dump(data, file, indent=2)
    
    print(f" Retrieved results saved to: {output_file}\n")
    
    # Print summary
    print("="*60)
    print("Projection Measurement Summary")
    print("="*60)
    
    for i, result in enumerate(updated_results):
        print(f"\nProblem {i+1}:")
        print(f"  Fidelity: {result['fidelity']:.4f}")
        print(f"  Avg success rate: {result['metadata']['average_success_rate']:.4f}")
        print(f"  Components: {result['metadata']['measured_components']}")
        print(f"  Solution: {result['reconstructed_solution_probabilities']}")
        
        # Show problem-level timing
        if 'total_problem_time_seconds' in result:
            print(f"  Total problem time: {result['total_problem_time_seconds']:.1f}s")
            print(f"    First created: {result['first_created_at']}")
            print(f"    Last ended: {result['last_ended_at']}")
        
        # Calculate timing statistics for this problem
        execution_times = []
        for task in result['projection_tasks']:
            exec_time = task.get('execution_time_seconds')
            if exec_time is not None:
                execution_times.append(exec_time)
        
        if execution_times:
            total_time = sum(execution_times)
            avg_time = np.mean(execution_times)
            min_time = min(execution_times)
            max_time = max(execution_times)
            print(f"  Task-level timing:")
            print(f"    Total execution time: {total_time:.1f}s")
            print(f"    Average per task: {avg_time:.1f}s")
            print(f"    Min/Max: {min_time:.1f}s / {max_time:.1f}s")
    
    print("\n" + "="*60)
    
    return output_path


def extract_solution_probability_from_counts(
    counts: dict, 
    target_basis_state: int,
    num_solution_qubits: int,
    debug: bool = False
) -> Tuple[float, float]:
    """
    Extract the probability of a specific basis state from measurement counts.
    
    Args:
        counts: Measurement counts dictionary from Braket
        target_basis_state: The basis state index we're measuring
        num_solution_qubits: Number of qubits encoding the solution
        debug: Print debug information
        
    Returns:
        (probability_given_success, overall_success_rate)
    """
    total_counts = sum(counts.values())
    success_counts = 0
    target_and_success_counts = 0
    
    target_bits = format(target_basis_state, f'0{num_solution_qubits}b')
    
    if debug:
        print(f"\n  Debug: Target |{target_basis_state}⟩ = |{target_bits}⟩")
    
    for bitstring, count in counts.items():
        bits = bitstring.replace(' ', '')
        
        # Flag qubit is rightmost bit
        flag_bit = int(bits[-1])
        
        # Solution qubits are leftmost bits (already in correct order)
        solution_bits = bits[:num_solution_qubits]
        
        if debug and success_counts < 3:
            print(f"  Bitstring: {bits}, flag={flag_bit}, solution={solution_bits}")
        
        if flag_bit == 1:
            success_counts += count
            if solution_bits == target_bits:
                target_and_success_counts += count
    
    overall_success_rate = success_counts / total_counts if total_counts > 0 else 0.0
    prob_given_success = target_and_success_counts / success_counts if success_counts > 0 else 0.0
    
    if debug:
        print(f"  Success rate: {overall_success_rate:.4f}")
        print(f"  P(target|success): {prob_given_success:.4f}")
    
    return prob_given_success, overall_success_rate


def reconstruct_solution_vector(
    projection_results: List[Dict],
    num_solution_qubits: int
) -> Tuple[np.ndarray, Dict]:
    """
    Reconstruct solution vector from projection measurement results.
    
    Args:
        projection_results: List of projection task results with counts
        num_solution_qubits: Number of qubits in solution register
        
    Returns:
        (solution_probabilities, metadata_dict)
    """
    dimension = 2**num_solution_qubits
    solution_probs = np.zeros(dimension)
    success_rates = []
    
    metadata = {
        'measured_components': [],
        'success_rates': [],
        'raw_probabilities': []
    }
    
    for proj_result in projection_results:
        if 'error' in proj_result or proj_result.get('counts') is None:
            continue
        
        basis_state = proj_result['basis_state']
        counts = proj_result['counts']
        
        prob, success_rate = extract_solution_probability_from_counts(
            counts, basis_state, num_solution_qubits
        )
        
        solution_probs[basis_state] = prob
        success_rates.append(success_rate)
        
        metadata['measured_components'].append(basis_state)
        metadata['success_rates'].append(success_rate)
        metadata['raw_probabilities'].append(prob)
    
    # Normalize probabilities
    total_prob = np.sum(solution_probs)
    if total_prob > 0:
        solution_probs /= total_prob
    
    metadata['average_success_rate'] = np.mean(success_rates) if success_rates else 0.0
    metadata['total_probability'] = float(total_prob)
    
    return solution_probs, metadata


def calculate_fidelity(measured_probs: np.ndarray, ideal_vector: np.ndarray) -> float:
    """
    Calculate fidelity between measured probabilities and ideal solution.
    
    Args:
        measured_probs: Probability distribution from measurements
        ideal_vector: Ideal solution statevector
        
    Returns:
        Fidelity value (0 to 1)
    """
    ideal_probs = np.abs(ideal_vector)**2
    ideal_probs /= np.sum(ideal_probs)
    
    fidelity = np.sum(np.sqrt(measured_probs * ideal_probs))**2
    
    return fidelity
