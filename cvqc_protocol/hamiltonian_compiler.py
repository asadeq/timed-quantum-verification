import numpy as np
import math
from qiskit import QuantumCircuit, QuantumRegister, transpile
from qiskit.quantum_info import Statevector

class HamiltonianCompiler:
    """
    Compiles a standard Quantum Circuit into a History State circuit 
    (|Psi_hist>) suitable for Local Hamiltonian verification.
    """
    def __init__(self, user_circuit: QuantumCircuit):
        self.user_circuit = user_circuit
        self.num_work_qubits = user_circuit.num_qubits
        
        # 1. Calculate Time Steps (T)
        # T = number of gates (or layers) in the user circuit
        self.num_time_steps = len(user_circuit.data)
        
        # 2. Calculate Clock Size
        # We need enough bits to represent times 0 to T.
        # e.g., 5 steps requires times 0..5 -> 3 bits.
        self.num_clock_qubits = math.ceil(math.log2(self.num_time_steps + 1))
        
        print(f"In Compiler - Input Circuit Depth: {self.num_time_steps}")
        print(f"In Compiler - Required Clock Qubits: {self.num_clock_qubits}")

    def _prepare(self):
        """
        Prepares the circuit for the Hamiltonian Compiler.
        1. Decomposes complex blocks (like Initialize/QFT) to expose hidden Resets.
        2. Removes non-unitary ops (Measure, Reset, Barrier).
        """
        print("In Compiler - Decomposing to basis gates...")

        qc = self.user_circuit
        
        basis = ['u', 'cx', 'h', 'p', 'cp', 'ry', 'rz', 'x', 'z', 'ccx']
        
        # Decompose to basis gates that expose resets and basic gates
        decomposed = transpile(qc, basis_gates=basis, optimization_level=1)
        clean_qc = QuantumCircuit(decomposed.qubits, decomposed.clbits)
        
        # Filter out non-unitary ops
        ignored_ops = ['measure', 'barrier', 'reset', 'save_statevector', 'snapshot']
        
        for instr in decomposed.data:
            if instr.operation.name not in ignored_ops:
                clean_qc.append(instr.operation, instr.qubits, instr.clbits)
            else:
                # Optional: Log what we removed
                # print(f"  > Removing non-unitary op: {instr.operation.name}")
                pass
                
        return clean_qc

    def compile(self):
        """
        Builds and returns the quantum circuit that prepares |Psi_hist>.
        state = sum(|t>_clock (X) |psi_t>_work)
        """
        clean_qc = self._prepare()

        # Create Registers
        clock_reg = QuantumRegister(self.num_clock_qubits, 'clock')
        work_reg = QuantumRegister(self.num_work_qubits, 'work')
        hist_qc = QuantumCircuit(clock_reg, work_reg)
        
        # A. INITIALIZE CLOCK SUPERPOSITION
        # Create uniform superposition of all time steps |0> + |1> + ... + |T>
        # (Simplified: applying H to all gives |0>...|2^N-1>. 
        # For exact history states, we usually just accept the 2^N range 
        # or accept that invalid times have 0 energy penalty in simpler models).
        hist_qc.h(clock_reg)
        
        hist_qc.barrier()
        
        # B. APPLY GATES CONDITIONALLY
        # Logic: Apply Gate_k ONLY if current time t >= k.
        
        # Iterate through the User's Circuit
        for k, instruction_ctx in enumerate(clean_qc.data):
            # step index k starts at 0, so this is Time Step k+1
            time_step = k + 1
            
            gate_op = instruction_ctx.operation
            qubit_indices = [clean_qc.find_bit(q).index for q in instruction_ctx.qubits]
            
            # Map user qubits to the Work Register in the new circuit
            target_qubits = [work_reg[i] for i in qubit_indices]
            
            self._apply_gate_for_valid_times(hist_qc, clock_reg, gate_op, target_qubits, time_step)
            
        hist_qc.barrier()
        return hist_qc

    def _apply_gate_for_valid_times(self, qc, clock_reg, gate_op, target_qubits, gate_time_step):
        """
        Applies the gate controlled on the condition: Clock >= gate_time_step.
        Since standard gates don't support ">= k", we sum over exact control states.
        """
        max_time = 2 ** self.num_clock_qubits
        
        # Iterate over every possible time t in the superposition
        for t in range(max_time):
            # The gate should have happened if the current time 't' is PAST this gate's step.
            if t >= gate_time_step:
                
                # Create Control String for time 't'
                # format(t, 'b') gives binary, zfill pads it.
                # Qiskit ctrl_state string is MSB...LSB (reversed relative to indexing?)
                # Actually Qiskit ctrl_state checks the string directly.
                time_bin_str = format(t, f'0{self.num_clock_qubits}b')
                
                # Create Controlled Gate
                # We control on the Clock Register matching exactly 'time_bin_str'
                c_gate = gate_op.control(self.num_clock_qubits, ctrl_state=time_bin_str)
                
                # Add to circuit
                qc.append(c_gate, list(clock_reg) + target_qubits)

    def get_statevector(self):
        """Helper to return the actual vector object for debugging."""
        qc = self.compile()
        return Statevector.from_instruction(qc)


if __name__ == "__main__":
    # 1. Define a User Circuit (e.g., Bell State)
    user_qc = QuantumCircuit(2)
    user_qc.h(0)
    user_qc.cx(0, 1)
    
    print("--- 1. User Circuit ---")
    print(user_qc)

    # 2. Compile to History State
    compiler = HamiltonianCompiler(user_qc)
    history_circuit = compiler.compile()

    print("\n--- 2. History State Circuit (Schematic) ---")
    # This will look messy because of the many controlled gates, 
    # but logically it implements the time evolution.
    print(history_circuit.draw(output='text', fold=120))

    # 3. Analyze the State (Debug)
    # The history state should be a superposition of:
    # |0>|00>  (Init)
    # |1>|+0>  (After H)
    # |2>|Phi+>(After CNOT)
    # |3>...   (If clock goes higher)
    
    sv = compiler.get_statevector()
    print("\n--- 3. History State Vector (Non-Zero Amplitudes) ---")
    
    # Pretty print the vector
    # Format: |Clock> |Work>
    # Note: Qiskit Statevector dict keys are little-endian strings: "Work Clock"
    data = sv.to_dict()
    for key, amp in data.items():
        if not np.isclose(abs(amp), 0):
            # Parse keys based on register sizes
            # Key string is like "q_work1 q_work0 q_clock1 q_clock0"
            clock_bits = key[0 : compiler.num_clock_qubits]
            work_bits = key[compiler.num_clock_qubits :]
            
            # Since Qiskit keys are reversed string order (LSB is rightmost char), 
            # let's just print the raw key for clarity or invert logic if needed.
            # Actually, let's just print raw to avoid confusion:
            print(f"State |{key}> : {amp:.3f}")

    print("\nInterpretation:")
    print("Each |Clock> value corresponds to a snapshot of the computation.")