import hashlib
class SequentialFunction:
    def __init__(self, difficulty_delay=0.0):
        self.delay = difficulty_delay

    # Should be changed into lattice
    def evaluate(self, x):
        """
        Computes f(x).
        """
        # Simulating work (optional delay)
        # time.sleep(self.delay) 
        
        # Simple SHA-256 hash to simulate a cryptographic function
        # We assume input x is bytes or string, output is bytes
        if isinstance(x, int):
            x = str(x).encode()
        elif isinstance(x, str):
            x = x.encode()
            
        return hashlib.sha256(x).digest()