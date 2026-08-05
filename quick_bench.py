"""Quick benchmark for PRGC fix."""
import secrets
import sys
from pathlib import Path

from timelock_puzzle.tlp_garbling import PythonGarbledTLP

print('=== SHA-256 mode ===')
for T in [1, 2, 4]:
    for mode in ['crgc', 'prgc']:
        correct = 0
        for _ in range(5):
            tlp = PythonGarbledTLP(T=T, use_sha256=True, garbling_mode=mode)
            pp = tlp.PSetup_Garble()
            s = secrets.randbits(1)
            Z = tlp.PGen(s, pp)
            rec = tlp.PSolve(Z, pp)
            if s == rec: correct += 1
        print(f'  T={T} {mode}: {correct}/5')

print('=== XOR mixing mode ===')
for T in [1, 2, 4]:
    for mode in ['crgc', 'prgc']:
        correct = 0
        for _ in range(5):
            tlp = PythonGarbledTLP(T=T, use_sha256=False, garbling_mode=mode)
            pp = tlp.PSetup_Garble()
            s = secrets.randbits(1)
            Z = tlp.PGen(s, pp)
            rec = tlp.PSolve(Z, pp)
            if s == rec: correct += 1
        print(f'  T={T} {mode}: {correct}/5')