# Publicly Verifiable Classical Verification of Quantum Computation via Time Locked Puzzles
TODO: WRITE description

## File Structure for garbled circuits with TLP flow:

* circuits/ - has sha256 circuit in bristol fashion 
* crgc_garbled_circuits/ - all the Circuit Garbling Components for Parsing, Garbling and Evaluating Circuits (Bristol format)
* crgc_garbled_circuits/scripts/ - the generator and evaluator scripts to test the garbling
* timelock_puzzle/sequential_functions.py - constructs sequential functions (Identity function, rotational XOR mixing, SHA256 with padding using circuit)
* timelock_puzzle/tlp_circuit_builder.py - uses sequential function to create TLP circuit by applying the function sequentially and then correclty adding the circuit's output wires (also defines the circuit gates builders for AND, NOT, XOR, OR and MUX)
* timelock_puzzle/tlp_garbling.py - Defines the input preparation, Psetup, PGen and PSolve for a TLP Circuit (using the tlp_Circiut_builder's create_tlp_unrolled_circuit builder)
* test_scripts/ - has a test of the full usage of garbled tlp setup, generation, solving adn verification using tlp_garbling