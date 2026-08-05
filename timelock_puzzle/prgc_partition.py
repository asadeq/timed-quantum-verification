"""
Helper for partitioning a TLP circuit into reusable (CRGC) and non-reusable
(Yao) sections for PRGC mode.

A gate is "non-reusable" if its output can be reached from any wire that
carries secret input — specifically:
  - All InputB wires (where m and z live in our TLP)
  - All InputA wires that the CRGC leakage predictor flags as leaked
    (i.e., reachable through a non-obfuscated path to the output)

The result is a set of gate indices that must be Yao-garbled instead of
CRGC-garbled. Everything else stays in the CRGC reusable section.
"""

from collections import deque
from typing import List, Set

from crgc_garbled_circuits.circuit_structures import TransformedCircuit
from crgc_garbled_circuits.leakage_predictor import (
    get_parents_of_each_wire,
    get_potentially_obfuscated_fixed_gates,
    get_potentially_intermediary_gates_from_output,
    get_leaked_inputs,
)


def find_non_reusable_gates(circuit: TransformedCircuit) -> Set[int]:
    """
    Return the set of gate indices that depend on secret input and must
    therefore be Yao-garbled (not CRGC-garbled) to preserve input privacy.

    Algorithm:
      1. Use the CRGC library's leakage predictor on InputA: walk from
         non-obfuscated gates backward to find which InputA bits can be
         inferred.
      2. Build a wire-to-children map (each gate's outputID -> list of
         downstream gates).
      3. BFS forward from every InputB wire AND every leaked-InputA wire,
         collecting every gate whose output is reachable.

    The resulting set is conservative: every gate whose output value can
    depend on `m` or `z` is marked non-reusable, regardless of whether the
    dependence is exploitable. This is the property PRGC needs.
    """
    num_wires = circuit.details.numWires
    inputa_len = circuit.details.bitlengthInputA
    inputb_len = circuit.details.bitlengthInputB
    num_outputs = circuit.details.numOutputs
    bitlength_outputs = circuit.details.bitlengthOutputs
    output_start = num_wires - num_outputs * bitlength_outputs

    # Step 1: identify leaked InputA wires using CRGC's existing machinery.
    # The library functions operate on a `po` (potentially-obfuscated) array
    # that tracks which wires can be determined from InputA alone.
    po = [False] * num_wires
    get_potentially_obfuscated_fixed_gates(circuit, po)
    parents = get_parents_of_each_wire(circuit)
    get_potentially_intermediary_gates_from_output(
        circuit.details, po, parents
    )
    leaked_inputa_indices = get_leaked_inputs(circuit, po)

    # Step 2: build children map (wire_id -> list of gate indices that
    # take this wire as input).
    children: List[List[int]] = [[] for _ in range(num_wires)]
    for gi, gate in enumerate(circuit.gates):
        children[gate.leftParentID].append(gi)
        children[gate.rightParentID].append(gi)

    # Step 3: BFS from sensitive input wires through the children map.
    # Sensitive wires = all InputB wires + leaked InputA wires (in the
    # forward wire-id space, which is what the gate graph uses).
    queue = deque()

    # All InputB wires
    for w in range(inputa_len, inputa_len + inputb_len):
        queue.append(w)

    # Leaked InputA wires — convert from "logical input index" (0..inputa_len-1,
    # LSB-first convention used by get_leaked_inputs) back to wire id.
    # The library convention: logical index i -> wire id inputa_len - 1 - i.
    for logical_idx in leaked_inputa_indices:
        wire_id = inputa_len - 1 - logical_idx
        queue.append(wire_id)

    reached_gates: Set[int] = set()
    while queue:
        w = queue.popleft()
        for gi in children[w]:
            if gi in reached_gates:
                continue
            # Don't Yao-garble output gates (they're plaintext in CRGC and
            # the TLP only needs the final output to be correct).
            if circuit.gates[gi].outputID >= output_start:
                continue
            reached_gates.add(gi)
            # Continue BFS through this gate's output
            out_w = circuit.gates[gi].outputID
            queue.append(out_w)

    return reached_gates


def find_reachable_inputB_wires(circuit: TransformedCircuit) -> Set[int]:
    """
    BFS forward from all InputB wires, returning the set of every wire whose
    value can depend on InputB. Used to determine which wires need Yao keys
    in PRGC mode (i.e., every wire downstream of InputB).
    """
    inputa_len = circuit.details.bitlengthInputA
    inputb_len = circuit.details.bitlengthInputB
    num_wires = circuit.details.numWires
    output_start = num_wires - circuit.details.numOutputs * circuit.details.bitlengthOutputs

    children: List[List[int]] = [[] for _ in range(num_wires)]
    for gate in circuit.gates:
        children[gate.leftParentID].append(gate.outputID)
        children[gate.rightParentID].append(gate.outputID)

    reached: Set[int] = set()
    queue = deque(range(inputa_len, inputa_len + inputb_len))
    while queue:
        w = queue.popleft()
        if w in reached:
            continue
        reached.add(w)
        if w >= output_start:
            continue
        for out_w in children[w]:
            queue.append(out_w)

    return reached
