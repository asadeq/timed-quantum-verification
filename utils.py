import hashlib

def random_oracle(y, m):
    """
    The Idealized Hash Function H.
    Set c := H(y) 
    """
    # Create a deterministic hash of the commitment y
    h = hashlib.sha256(y.encode('utf-8')).hexdigest()
    
    # Convert hex hash to a binary string of length m (the challenge string)
    # We take the integer value and format it as binary.
    binary_c = bin(int(h, 16))[2:].zfill(256) 
    
    # Truncate or pad to exactly length m
    return binary_c[:m]