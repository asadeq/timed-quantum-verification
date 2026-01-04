from abc import ABC, abstractmethod
from typing import Any, List

class GateBackend(ABC):
    """
    The Abstract Base Class. 
    Any crypto scheme (HLL23, OpenFHE, TFHE) must implement these 3 methods.
    """
    @abstractmethod
    def encrypt(self, value: int) -> Any:
        """Entry point: Converts integer (0/1) to Ciphertext/WireLabel."""
        pass

    @abstractmethod
    def decrypt(self, ct: Any) -> int:
        """Exit point: Converts Ciphertext/WireLabel back to integer."""
        pass

    @abstractmethod
    def nand(self, a: Any, b: Any) -> Any:
        """The Universal Gate."""
        pass

    # --- Derived Gates (Default implementations, can be overridden) ---
    def not_gate(self, a): return self.nand(a, a)
    def and_gate(self, a, b): return self.not_gate(self.nand(a, b))
    def or_gate(self, a, b): return self.nand(self.not_gate(a), self.not_gate(b))
    def xor_gate(self, a, b):
        # Optimized NAND construction for XOR
        n1 = self.nand(a, b)
        n2 = self.nand(a, n1)
        n3 = self.nand(b, n1)
        return self.nand(n2, n3)