"""Callback-driven MC6809/HD6309 emulation and assembler tools."""

from .mc6809 import CPU, MC6809, HD6309, Registers, IllegalInstruction
from .ins6809 import (
    AddrMode, OperandType, Instruction, INSTRUCTIONS, BY_OPCODE, BY_MNEMONIC,
    disassemble_one, format_line,
)

__all__ = [
    "CPU", "MC6809", "HD6309", "Registers", "IllegalInstruction",
    "AddrMode", "OperandType", "Instruction", "INSTRUCTIONS", "BY_OPCODE",
    "BY_MNEMONIC", "disassemble_one", "format_line",
    "Assembler", "AssemblyError", "AssemblyResult",
]


def __getattr__(name):
    # Keep `python -m mc6809.asm6809` free of eager-import warnings.
    if name in ("Assembler", "AssemblyError", "AssemblyResult"):
        from . import asm6809
        value = getattr(asm6809, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
