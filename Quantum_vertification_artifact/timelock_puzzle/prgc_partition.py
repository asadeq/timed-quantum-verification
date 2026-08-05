"""Partition a TLP circuit into reusable (CRGC) and non-reusable (Yao) gates.

A gate is "non-reusable" if its output is reachable from any InputB wire
(carries m/z) or from any leaked-InputA wire (flagged by the CRGC leakage
predictor). The BFS is conservative: every gate whose value can depend on
m or z is marked non-reusable. See README §"Garbling modes".
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
    """Return gate indices whose outputs depend on secret input."""
    num_wires = circuit.details.numWires
    inputa_len = circuit.details.bitlengthInputA
    inputb_len = circuit.details.bitlengthInputB
    output_start = num_wires - circuit.details.numOutputs * circuit.details.bitlengthOutputs

    # Step 1: find leaked InputA wires via the CRGC leakage predictor.
    po = [False] * num_wires
    get_potentially_obfuscated_fixed_gates(circuit, po)
    parents = get_parents_of_each_wire(circuit)
    get_potentially_intermediary_gates_from_output(circuit.details, po, parents)
    leaked_inputa_indices = get_leaked_inputs(circuit, po)

    # Step 2: build children map (wire_id -> list of consuming gate indices).
    children: List[List[int]] = [[] for _ in range(num_wires)]
    for gi, gate in enumerate(circuit.gates):
        children[gate.leftParentID].append(gi)
        children[gate.rightParentID].append(gi)

    # Step 3: BFS from sensitive wires and collect reachable non-output gates.
    queue = deque()
    for w in range(inputa_len, inputa_len + inputb_len):
        queue.append(w)
    for logical_idx in leaked_inputa_indices:
        # Library uses LSB-first logical indices; convert to wire id.
        queue.append(inputa_len - 1 - logical_idx)

    reached_gates: Set[int] = set()
    while queue:
        w = queue.popleft()
        for gi in children[w]:
            if gi in reached_gates:
                continue
            if circuit.gates[gi].outputID >= output_start:
                continue  # outputs stay plaintext in CRGC
            reached_gates.add(gi)
            queue.append(circuit.gates[gi].outputID)

    return reached_gates


def find_reachable_inputB_wires(circuit: TransformedCircuit) -> Set[int]:
    """BFS forward from all InputB wires; return every wire that can depend on InputB."""
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
