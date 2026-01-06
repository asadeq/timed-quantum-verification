import numpy as np
import json
import hashlib

# =======================
# Parameters
# =======================

q = 8192                   # modulus (must be power of 2 for simplicity)
n = 128                    # dimension of lattice
logq = q.bit_length()      # number of bits to represent q

# =======================
# Lattice Utilities
# =======================

def bit_decompose(vec, width=logq):
    """
    Decomposes a vector in Z_q^n into bits (mod 2).
    Returns a flat bit vector.
    """
    bits = []
    for val in vec:
        for i in range(width):
            bits.append((val >> i) & 1)
    return np.array(bits, dtype=np.uint8)

def hash_to_vector(data: bytes, length: int = n) -> np.ndarray:
    """
    Hashes `data` into a vector in Z_q^length using SHAKE-256.
    """
    shake = hashlib.shake_256()
    shake.update(data)
    raw = shake.digest(length * 2)  # 2 bytes per entry
    vec = [int.from_bytes(raw[i:i+2], 'little') % q for i in range(0, len(raw), 2)]
    return np.array(vec, dtype=np.int64)

def sequential_lattice_function(A: np.ndarray, x: np.ndarray) -> np.ndarray:
    """
    f(x) = G⁻¹(Ax mod q)
    """
    assert x.shape == (n,), f"x must be shape ({n},), got {x.shape}"
    Ax = (A @ x) % q
    bits = bit_decompose(Ax, width=logq)
    return hash_to_vector(bits.tobytes(), length=n)

def sequential_lattice_chain(A: np.ndarray, x0: np.ndarray, T: int) -> np.ndarray:
    """
    Repeated application: f^T(x)
    """
    x = x0.copy()
    for _ in range(T):
        x = sequential_lattice_function(A, x)
    return x

# =======================
# Helper: Convert between bytes and vectors
# =======================

def bytes_to_vector(b: bytes, length=n) -> np.ndarray:
    x = np.frombuffer(b, dtype=np.uint8)
    if len(x) < length:
        x = np.pad(x, (0, length - len(x)), 'constant')
    return x[:length].astype(np.int64) % q

def vector_to_bytes(v: np.ndarray, out_len=32) -> bytes:
    return v.astype(np.uint8).tobytes()[:out_len]

# =======================
# Puzzle Functions
# =======================

def generate_puzzle(T: int, message: bytes) -> dict:
    """
    Generate a time-lock puzzle using lattice sequential function.
    """
    assert len(message) <= 32, "Message too long for this demo."

    A = np.random.randint(0, q, size=(n, n), dtype=np.int64)   # Public matrix
    x0 = np.random.randint(0, q, size=(n,), dtype=np.int64)    # Random seed

    fTx = sequential_lattice_chain(A, x0, T)
    fTx_bytes = vector_to_bytes(fTx, len(message))

    ciphertext = bytes([m ^ k for m, k in zip(message, fTx_bytes)])

    return {
        'T': T,
        'ciphertext': ciphertext.hex(),
        'x0': x0.tolist(),
        'A': A.tolist(),
    }

def solve_puzzle(puzzle: dict) -> bytes:
    """
    Solve the time-lock puzzle by computing f^T(x0)
    """
    T = puzzle['T']
    ciphertext = bytes.fromhex(puzzle['ciphertext'])
    A = np.array(puzzle['A'], dtype=np.int64)
    x0 = np.array(puzzle['x0'], dtype=np.int64)

    fTx = sequential_lattice_chain(A, x0, T)
    fTx_bytes = vector_to_bytes(fTx, len(ciphertext))

    message = bytes([c ^ k for c, k in zip(ciphertext, fTx_bytes)])
    return message

if __name__ == "__main__":
    T = 2**12  # Use small T for demonstration; large T will increase delay
    message = b"This is a secret msg!"

    print("[*] Generating puzzle...")
    puzzle = generate_puzzle(T, message)
    with open("puzzle.json", "w") as f:
        json.dump(puzzle, f)

    print("[*] Puzzle generated and saved to 'puzzle.json'.")
    print("    Ciphertext:", puzzle['ciphertext'])

    print("[*] Solving puzzle...")
    with open("puzzle.json", "r") as f:
        loaded_puzzle = json.load(f)

    recovered = solve_puzzle(loaded_puzzle)
    print("    Recovered Message:", recovered.decode())
