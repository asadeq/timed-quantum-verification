"""
CRGC - Completely Reusable Garbled Circuits
Python implementation for Bristol Fashion circuit processing
"""

from .circuit_structures import CircuitDetails, TransformedGate, TransformedCircuit
from .helper_functions import (
    int_to_bool_array,
    bool_array_to_int,
    swap_left_parent,
    swap_right_parent,
    flip_table,
    generate_random_input,
    generate_random_bool,
    parse_input
)
from .circuit_reader import (
    import_bristol_circuit_details,
    import_bristol_circuit_ex_not,
    import_transformed_circuit,
    import_obfuscated_input
)
from .circuit_evaluator import (
    evaluate_transformed_circuit,
    evaluate_sorted_transformed_circuit
)
from .circuit_flipper import (
    obfuscate_input,
    get_flipped_circuit
)
from .circuit_obfuscator import identify_fixed_gates_arr
from .circuit_integrity_breaker import (
    get_intermediary_gates_from_output,
    regenerate_gates
)
from .circuit_writer import (
    export_circuit_separate_files,
    export_obfuscated_input
)
from .leakage_predictor import (
    get_parents_of_each_wire,
    get_potentially_obfuscated_fixed_gates,
    get_potentially_intermediary_gates_from_output,
    get_leaked_inputs
)
from .python_to_circuit import (
    PythonCircuitCompiler,
    export_to_bristol
)

__all__ = [
    'CircuitDetails', 'TransformedGate', 'TransformedCircuit',
    'int_to_bool_array', 'bool_array_to_int',
    'swap_left_parent', 'swap_right_parent', 'flip_table',
    'generate_random_input', 'generate_random_bool', 'parse_input',
    'import_bristol_circuit_details', 'import_bristol_circuit_ex_not',
    'import_transformed_circuit', 'import_obfuscated_input',
    'evaluate_transformed_circuit', 'evaluate_sorted_transformed_circuit',
    'obfuscate_input', 'get_flipped_circuit',
    'identify_fixed_gates_arr',
    'get_intermediary_gates_from_output', 'regenerate_gates',
    'export_circuit_separate_files', 'export_obfuscated_input',
    'get_parents_of_each_wire', 'get_potentially_obfuscated_fixed_gates',
    'get_potentially_intermediary_gates_from_output', 'get_leaked_inputs',
    'PythonCircuitCompiler', 'export_to_bristol'
]
