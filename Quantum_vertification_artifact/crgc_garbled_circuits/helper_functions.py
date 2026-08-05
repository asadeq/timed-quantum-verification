"""
Helper functions for CRGC circuit processing
Utilities for conversions, random generation, and truth table manipulation
"""

import secrets
from typing import List
from pathlib import Path


def int_to_bool_array(num: int, bitlength: int) -> List[bool]:
    """
    Convert integer to boolean array
    
    Args:
        num: Integer to convert
        bitlength: Number of bits in output array
    
    Returns:
        Boolean array with MSB first
    """
    arr = []
    for i in range(bitlength):
        arr.insert(0, bool(num & 1))
        num >>= 1
    return arr


def bool_array_to_int(arr: List[bool]) -> int:
    """
    Convert boolean array to integer
    
    Args:
        arr: Boolean array with MSB first
    
    Returns:
        Integer value
    """
    num = 0
    for i, bit in enumerate(arr):
        num |= (int(bit) << (len(arr) - i - 1))
    return num


def swap_left_parent(truth_table: List[List[bool]]) -> None:
    """
    Swap rows 0 and 1 in truth table (for left parent flip)
    Modifies truth_table in place
    
    Args:
        truth_table: 2x2 truth table to modify
    """
    truth_table[0][0], truth_table[1][0] = truth_table[1][0], truth_table[0][0]
    truth_table[0][1], truth_table[1][1] = truth_table[1][1], truth_table[0][1]


def swap_right_parent(truth_table: List[List[bool]]) -> None:
    """
    Swap columns 0 and 1 in truth table (for right parent flip)
    Modifies truth_table in place
    
    Args:
        truth_table: 2x2 truth table to modify
    """
    truth_table[0][0], truth_table[0][1] = truth_table[0][1], truth_table[0][0]
    truth_table[1][0], truth_table[1][1] = truth_table[1][1], truth_table[1][0]


def flip_table(truth_table: List[List[bool]]) -> None:
    """
    Invert all values in truth table
    Modifies truth_table in place
    
    Args:
        truth_table: 2x2 truth table to modify
    """
    truth_table[0][0] = not truth_table[0][0]
    truth_table[0][1] = not truth_table[0][1]
    truth_table[1][0] = not truth_table[1][0]
    truth_table[1][1] = not truth_table[1][1]


def generate_random_bool() -> bool:
    """
    Generate a cryptographically secure random boolean
    Uses secrets module for high-quality randomness
    
    Returns:
        Random boolean value
    """
    return secrets.randbits(1) == 1


def generate_random_input(bitlength: int) -> List[bool]:
    """
    Generate random input array
    
    Args:
        bitlength: Number of random bits to generate
    
    Returns:
        List of random boolean values
    """
    return [generate_random_bool() for _ in range(bitlength)]


def parse_input(input_arg: str, bitlength: int, circuit_name: str, input_type: str) -> List[bool]:
    """
    Parse input argument (random, integer, or filename)
    
    Args:
        input_arg: Input specification ('r' for random, number, or filename)
        bitlength: Expected bit length
        circuit_name: Circuit name for file path
        input_type: 'A' or 'B' for input type
    
    Returns:
        Boolean array of specified length
    """
    if input_arg == 'r':
        # Generate random input
        return generate_random_input(bitlength)
    
    # Try to parse as integer
    try:
        num = int(input_arg)
        return int_to_bool_array(num, bitlength)
    except ValueError:
        pass
    
    # Try to read from file
    filepath = Path(f"../src/circuits/{circuit_name}_input{input_type}.txt")
    if filepath.exists():
        with open(filepath, 'r') as f:
            binary_str = f.read().strip()
            if len(binary_str) != bitlength:
                raise ValueError(f"Input file has {len(binary_str)} bits, expected {bitlength}")
            return [c == '1' for c in binary_str]
    
    raise ValueError(f"Could not parse input: {input_arg}")


def check_number(s: str) -> bool:
    """
    Check if string is a valid number
    
    Args:
        s: String to check
    
    Returns:
        True if string represents a number
    """
    try:
        int(s)
        return True
    except ValueError:
        return False
