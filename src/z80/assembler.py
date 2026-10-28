"""Two-pass Z80 assembler driven by the public instruction catalogue."""

import ast
import argparse
import operator
import re
from dataclasses import dataclass
from pathlib import Path
from .instructions import INSTRUCTIONS


class AssemblyError(ValueError):
    pass


_OP = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitAnd: operator.and_,
    ast.BitXor: operator.xor,
}


def expression(text, symbols, pc, unresolved=False):
    text = re.sub(r"\$([0-9a-f]+)", r"0x\1", text, flags=re.I)
    text = re.sub(r"\b([0-9][0-9a-f]*)h\b", r"0x\1", text, flags=re.I)
    if text.strip() == "$":
        return pc

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return n.value
        if isinstance(n, ast.Name):
            if n.id.upper() in symbols:
                return symbols[n.id.upper()]
            if unresolved:
                return 0
            raise AssemblyError(f"unknown symbol {n.id}")
        if isinstance(n, ast.BinOp) and type(n.op) in _OP:
            return _OP[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(
            n.op, (ast.UAdd, ast.USub, ast.Invert)
        ):
            v = ev(n.operand)
            return (
                v
                if isinstance(n.op, ast.UAdd)
                else -v if isinstance(n.op, ast.USub) else ~v
            )
        raise AssemblyError("unsupported expression")

    try:
        return ev(ast.parse(text, mode="eval").body)
    except (SyntaxError, ZeroDivisionError, ValueError) as exc:
        raise AssemblyError(str(exc)) from exc


def normalize(t):
    return re.sub(r"\s+", "", t).upper()


def pattern(i):
    t = i.operands
    parts = []
    names = []
    pos = 0
    for match in re.finditer(r"nn|n|e|\+d", t):
        parts.append(re.escape(normalize(t[pos : match.start()])))
        names.append(match.group())
        parts.append(r"([+-][^,()]+)" if match.group() == "+d" else r"([^,()]+)")
        pos = match.end()
    parts.append(re.escape(normalize(t[pos:])))
    return re.compile("^" + "".join(parts) + "$"), names


_FORMS = []
for _i in INSTRUCTIONS:
    _pat, _names = pattern(_i)
    _FORMS.append((_i, _pat, _names))
# Literal register/condition forms must win over generic immediate forms.
_FORMS.sort(
    key=lambda entry: (
        len(entry[2]),
        entry[0].undocumented,
        -len(entry[0].operands),
        len(entry[0].opcode),
    )
)
_RESERVED = {
    "A",
    "B",
    "C",
    "D",
    "E",
    "H",
    "L",
    "AF",
    "BC",
    "DE",
    "HL",
    "SP",
    "IX",
    "IY",
    "IXH",
    "IXL",
    "IYH",
    "IYL",
    "I",
    "R",
    "NZ",
    "Z",
    "NC",
    "PO",
    "PE",
    "P",
    "M",
}


@dataclass
class AssemblyResult:
    memory: bytearray
    used: set
    symbols: dict

    @property
    def range(self):
        return (min(self.used), max(self.used) + 1) if self.used else None

    def binary(self, full=True):
        span = self.range
        return (
            bytes(self.memory)
            if full
            else bytes(self.memory[slice(*span)]) if span else b""
        )

    def intel_hex(self):
        out = []
        addresses = sorted(self.used)
        p = 0
        while p < len(addresses):
            start = addresses[p]
            data = []
            while (
                p < len(addresses)
                and addresses[p] == start + len(data)
                and len(data) < 16
            ):
                data.append(self.memory[addresses[p]])
                p += 1
            rec = bytes([len(data), start >> 8, start & 255, 0] + data)
            out.append(":" + rec.hex().upper() + f"{(-sum(rec))&255:02X}")
        return "\n".join(out + [":00000001FF"]) + "\n"


class Assembler:
    def __init__(self, *, i8080_only=False, allow_undocumented=False, fill=0):
        if not 0 <= fill <= 255:
            raise ValueError("fill must be 0..255")
        self.i8080_only = i8080_only
        self.allow_undocumented = allow_undocumented
        self.fill = fill

    def _encode(self, mnemonic, operands, symbols, pc, sizing):
        if mnemonic == "RST":
            value = expression(operands, symbols, pc, sizing)
            if value not in range(0, 64, 8):
                raise AssemblyError("RST vector must be 0,8,...,56")
            operands = f"{value:02X}H"
        for i, pat, names in _FORMS:
            if (
                i.mnemonic != mnemonic
                or self.i8080_only
                and not i.is_i8080
                or i.undocumented
                and not self.allow_undocumented
            ):
                continue
            match = pat.fullmatch(normalize(operands))
            if not match:
                continue
            groups = match.groups()
            if any(
                set(
                    re.findall(
                        r"[A-Z_][A-Z_0-9]*",
                        re.sub(
                            r"\$[0-9A-F]+|0X[0-9A-F]+|\b[0-9][0-9A-F]*H\b",
                            "",
                            normalize(g),
                        ),
                    )
                )
                & _RESERVED
                for g in groups
            ):
                continue
            # Bare immediates cannot consume indirect operand syntax.
            values = [expression(g, symbols, pc, sizing) for g in groups]
            extra = []
            displacement = None
            for kind, v in zip(names, values):
                if kind == "e":
                    v = (v - (pc + i.byte_count)) & 65535
                    if v >= 32768:
                        v -= 65536
                if not sizing:
                    if kind in ("e", "+d") and not -128 <= v <= 127:
                        raise AssemblyError("relative offset outside -128..127")
                    if kind == "n" and not -128 <= v <= 255:
                        raise AssemblyError("byte outside -128..255")
                    if kind == "nn" and not -32768 <= v <= 65535:
                        raise AssemblyError("word outside -32768..65535")
                if kind == "+d" and i.displacement_before_opcode:
                    displacement = v & 255
                else:
                    extra.append(v & 255)
                    if kind == "nn":
                        extra.append((v >> 8) & 255)
            if i.displacement_before_opcode:
                return i.opcode[:2] + bytes([displacement]) + i.opcode[2:]
            return i.opcode + bytes(extra)
        raise AssemblyError(f"unsupported instruction: {mnemonic} {operands}")

    def assemble(self, source):
        statements = []
        for no, line in enumerate(source.splitlines(), 1):
            # Comments outside quoted strings only.
            line = re.split(r";(?=(?:[^\"\']|\"[^\"]*\"|\'[^\']*\')*$)", line, 1)[
                0
            ].strip()
            label = None
            if ":" in line:
                label, line = line.split(":", 1)
                label = label.strip().upper()
                line = line.strip()
            fields = line.split(None, 2)
            if len(fields) >= 2 and fields[1].upper() == "EQU":
                label = fields[0].upper()
                line = "EQU " + (fields[2] if len(fields) > 2 else "")
            fields = line.split(None, 1)
            mnemonic = fields[0].upper() if fields else ""
            operands = fields[1] if len(fields) > 1 else ""
            statements.append((no, label, mnemonic, operands))
        symbols = {}
        memory = bytearray([self.fill]) * 65536
        used = set()
        for sizing in (True, False):
            pc = 0
            seen = set()
            for no, label, mnemonic, operands in statements:
                try:
                    if label:
                        if not re.fullmatch("[A-Z_][A-Z_0-9]*", label) or label in seen:
                            raise AssemblyError("invalid or duplicate label")
                        seen.add(label)
                        if mnemonic != "EQU":
                            symbols[label] = pc
                    if not mnemonic:
                        continue
                    if mnemonic == "END":
                        break
                    if mnemonic == "ORG":
                        # Layout directives require already known expressions.
                        pc = expression(operands, symbols, pc)
                        if not 0 <= pc <= 65535:
                            raise AssemblyError("ORG outside address space")
                        continue
                    if mnemonic == "EQU":
                        if not label:
                            raise AssemblyError("EQU requires a label")
                        symbols[label] = expression(operands, symbols, pc)
                        continue
                    if mnemonic in ("DS", "RMB"):
                        count = expression(operands, symbols, pc)
                        if count < 0 or pc + count > 65536:
                            raise AssemblyError("reservation outside address space")
                        pc += count
                        continue
                    if mnemonic in ("DB", "DEFB", "BYTE", "DW", "DEFW", "WORD"):
                        data = bytearray()
                        word = mnemonic in ("DW", "DEFW", "WORD")
                        for part in re.split(r",(?=(?:[^\"]|\"[^\"]*\")*$)", operands):
                            part = part.strip()
                            if part.startswith('"') and not word:
                                data.extend(ast.literal_eval(part).encode("latin1"))
                                continue
                            value = expression(part, symbols, pc, sizing)
                            if not sizing and not (
                                -32768 <= value <= 65535
                                if word
                                else -128 <= value <= 255
                            ):
                                raise AssemblyError("data out of range")
                            data.append(value & 255)
                            if word:
                                data.append((value >> 8) & 255)
                    else:
                        data = self._encode(mnemonic, operands, symbols, pc, sizing)
                    if pc + len(data) > 65536:
                        raise AssemblyError("output crosses address-space boundary")
                    if not sizing:
                        for offset, v in enumerate(data):
                            address = pc + offset
                            if address in used:
                                raise AssemblyError("overlapping output")
                            memory[address] = v
                            used.add(address)
                    pc += len(data)
                except (AssemblyError, ValueError, TypeError) as exc:
                    raise AssemblyError(f"line {no}: {exc}") from exc
        return AssemblyResult(memory, used, symbols)


def main():
    p = argparse.ArgumentParser(description="Z80 assembler (Zilog syntax)")
    p.add_argument("source", type=Path)
    p.add_argument("-o", "--output", required=True, type=Path)
    p.add_argument("--i8080-only", action="store_true")
    p.add_argument("--undocumented", action="store_true")
    p.add_argument("--trim", action="store_true")
    p.add_argument("--format", choices=["bin", "hex"], default="bin")
    args = p.parse_args()
    try:
        result = Assembler(
            i8080_only=args.i8080_only, allow_undocumented=args.undocumented
        ).assemble(args.source.read_text())
        if args.format == "hex":
            args.output.write_text(result.intel_hex())
        else:
            args.output.write_bytes(result.binary(not args.trim))
    except (AssemblyError, OSError) as exc:
        p.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    main()
