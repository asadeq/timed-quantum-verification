import secrets
from timelock_puzzle.reusable_garbled_circuit import ReusableGarbledCircuit
from timelock_puzzle.lattice_sequential_function import SequentialFunction

class TimeLockPuzzle:
    """
    The TLP Construction from Section 4 of Agrawal et al. (2024).
    """
    def __init__(self, security_param=256, T=1000):
        self.T = T
        self.lam = security_param
        self.seq_func = SequentialFunction()
        self.rgc = ReusableGarbledCircuit()

    def _step_circuit(self, b, x, m, z, i):
        """
        The Circuit C(b, x, m, z, i) defined in the paper
        This represents ONE step of the computation.
        """
        # Logic:
        # If i = T + 1:
        #   If b = 0: Return m
        #   If b = 1: Return x XOR z
        # Otherwise: Return (b, f(x), m, z, i+1)
        
        if i == self.T + 1:
            if b == 0:
                return m
            elif b == 1:
                # x XOR z (assuming byte strings of same length)
                # Helper for XORing bytes
                return bytes(a ^ b for a, b in zip(x, z))
        else:
            # Recursive step: return state for next iteration
            return (b, self.seq_func.evaluate(x), m, z, i + 1)
        return None

    def _circuit_T_repetition(self, b, x, m, z, i):
        """
        Represents C_T, the T-fold repetition of the step circuit.
        This is the actual function evaluated by rGC.Eval.
        """
        current_b, current_x, current_m, current_z, current_i = b, x, m, z, i
        
        # We run the loop until i reaches T + 1 to trigger the output condition
        # The paper implies C_T encapsulates the T steps.
        # Given input i=1, we need T steps to reach i=T+1.
        
        while current_i <= self.T + 1:
            result = self._step_circuit(current_b, current_x, current_m, current_z, current_i)
            
            # Check if result is the final output (bytes) or next state (tuple)
            if isinstance(result, tuple):
                (current_b, current_x, current_m, current_z, current_i) = result
            else:
                return result # Final output (m or x^z)
                
        return None

    def setup(self):
        """
        PSetup(1^lambda, T)
        Generates public parameters pp = (C_tilde, pk).
        """
        # Garble the T-fold repetition circuit C_T
        C_tilde, pk = self.rgc.garble(self.lam, self._circuit_T_repetition)
        pp = (C_tilde, pk)
        print(f"Setup complete. Parameters generated for T={self.T}.")
        return pp

    def generate(self, pp, s_bit):
        """
        PGen(pp, s)
        Encrypts a solution 's' (bit) into a puzzle Z.
        """
        C_tilde, pk = pp
        
        # 1. Sample random x, m, r from {0,1}^lambda
        # We use simple 32-byte strings for simulation
        x = secrets.token_bytes(32)
        m = secrets.token_bytes(32)
        r = secrets.token_bytes(32)
        
        # 2. Compute x_tilde <- rGC.Enc(pk, (0, x, m, 0^lambda, 1)) 
        # Initial inputs: b=0, x=x, m=m, z=0, i=1
        z_zero = bytes(32) # 0^lambda
        input_tuple = (0, x, m, z_zero, 1)
        x_tilde = self.rgc.encode(pk, input_tuple)
        
        # 3. Compute Goldreich-Levin predicate: (r . m) XOR s 
        # Inner product of bits of r and m mod 2
        r_int = int.from_bytes(r, 'big')
        m_int = int.from_bytes(m, 'big')
        
        # Calculate dot product parity
        dot_product = bin(r_int & m_int).count('1') % 2
        masked_s = dot_product ^ s_bit
        
        # Return Z = (x_tilde, r, masked_s)
        puzzle_Z = (x_tilde, r, masked_s)
        print("Puzzle generated.")
        return puzzle_Z

    def solve(self, pp, puzzle_Z):
        """
        PSolve(Z)
        """
        x_tilde, r, masked_s = puzzle_Z
        C_tilde, pk = pp # Unpack public parameters
        
        print("Solving puzzle (this involves sequential work)...")
        
        # 1. Compute y <- rGC.Eval(C_tilde, C_T, x_tilde)
        # Based on the circuit logic with b=0, this returns 'm'
        y = self.rgc.eval(C_tilde, self._circuit_T_repetition, x_tilde)
        
        # y should be 'm'
        m_recovered = y
        
        # 2. Use y . r to unmask s 
        m_int = int.from_bytes(m_recovered, 'big')
        r_int = int.from_bytes(r, 'big')
        
        dot_product = bin(m_int & r_int).count('1') % 2
        
        s_recovered = masked_s ^ dot_product
        return s_recovered

if __name__ == "__main__":
    # 1. Initialize TLP with Time parameter T=1000
    # In a real scenario, T would be much larger.
    tlp = TimeLockPuzzle(T=2**20)
    pp = tlp.setup()
    
    # 2. The secret solution we want to hide (0 or 1)
    secret_bit = 1
    print(f"Original Secret: {secret_bit}")
    
    # 3. Generate the Puzzle
    puzzle = tlp.generate(pp, secret_bit)
    
    # 4. Solve the Puzzle
    # This runs the 'sequential' function T times inside the 'eval' step.
    recovered_secret = tlp.solve(pp, puzzle)

    print(f"Recovered Secret: {recovered_secret}")
    
    assert secret_bit == recovered_secret
    print("Success!")