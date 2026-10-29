"""Z80 CPU emulation, instruction metadata, assembler and disassembler."""

from .cpu import Z80, CPU, Registers
from .instructions import (
    Instruction,
    INSTRUCTIONS,
    BY_OPCODE,
    BY_MNEMONIC,
    Decoded,
    disassemble_one,
    format_line,
)

__all__ = [
    "Z80",
    "CPU",
    "Registers",
    "Instruction",
    "INSTRUCTIONS",
    "BY_OPCODE",
    "BY_MNEMONIC",
    "Decoded",
    "disassemble_one",
    "format_line",
]

__all__ += ["Assembler", "AssemblyError", "AssemblyResult"]


def __getattr__(name):
    # Keep `python -m z80.assembler` free of eager-import warnings.
    if name in ("Assembler", "AssemblyError", "AssemblyResult"):
        from . import assembler
        value = getattr(assembler, name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
