"""Algorithmic Z80 instruction catalogue, including common undocumented forms.

is_i8080 means a documented Intel 8080 counterpart with the same opcode and
operand encoding. It does not promise identical flags or cycle timing.
"""

from dataclasses import dataclass, replace
from collections import defaultdict


@dataclass(frozen=True)
class Instruction:
    mnemonic: str
    operands: str
    opcode: bytes
    byte_count: int
    cycles: int
    cycles_taken: int | None = None
    is_i8080: bool = False
    undocumented: bool = False
    displacement_before_opcode: bool = False

    @property
    def text(self):
        return self.mnemonic + (" " + self.operands if self.operands else "")


_items = []


def add(op, text, cycles, taken=None, intel=False, undocumented=False):
    mnemonic, _, operands = text.partition(" ")
    extra = (
        operands.count("nn") * 2
        + operands.replace("nn", "").count("n")
        + operands.count("e")
    )
    _items.append(
        Instruction(
            mnemonic,
            operands,
            bytes(op),
            len(op) + extra,
            cycles,
            taken,
            intel,
            undocumented,
        )
    )


R = ("B", "C", "D", "E", "H", "L", "(HL)", "A")
RP = ("BC", "DE", "HL", "SP")
RP2 = ("BC", "DE", "HL", "AF")
CC = ("NZ", "Z", "NC", "C", "PO", "PE", "P", "M")
ALU = ("ADD A,", "ADC A,", "SUB ", "SBC A,", "AND ", "XOR ", "OR ", "CP ")
for op in range(256):
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1
    if x == 0:
        if z == 0:
            t = (
                "NOP",
                "EX AF,AF'",
                "DJNZ e",
                "JR e",
                "JR NZ,e",
                "JR Z,e",
                "JR NC,e",
                "JR C,e",
            )[y]
            add(
                [op],
                t,
                (4, 4, 8, 12, 7, 7, 7, 7)[y],
                13 if y == 2 else 12 if y >= 4 else None,
                y == 0,
            )
        elif z == 1:
            add(
                [op],
                f"LD {RP[p]},nn" if not q else f"ADD HL,{RP[p]}",
                10 if not q else 11,
                intel=True,
            )
        elif z == 2:
            t = (
                ("LD (BC),A", "LD (DE),A", "LD (nn),HL", "LD (nn),A")
                if not q
                else ("LD A,(BC)", "LD A,(DE)", "LD HL,(nn)", "LD A,(nn)")
            )[p]
            add([op], t, (7, 7, 16, 13)[p], intel=True)
        elif z == 3:
            add([op], f'{"DEC" if q else "INC"} {RP[p]}', 6, intel=True)
        elif z in (4, 5):
            add(
                [op],
                f'{"INC" if z==4 else "DEC"} {R[y]}',
                11 if y == 6 else 4,
                intel=True,
            )
        elif z == 6:
            add([op], f"LD {R[y]},n", 10 if y == 6 else 7, intel=True)
        else:
            add(
                [op],
                ("RLCA", "RRCA", "RLA", "RRA", "DAA", "CPL", "SCF", "CCF")[y],
                4,
                intel=True,
            )
    elif x == 1:
        add(
            [op],
            "HALT" if op == 0x76 else f"LD {R[y]},{R[z]}",
            7 if 6 in (y, z) and op != 0x76 else 4,
            intel=True,
        )
    elif x == 2:
        add([op], ALU[y] + R[z], 7 if z == 6 else 4, intel=True)
    elif z == 0:
        add([op], f"RET {CC[y]}", 5, 11, True)
    elif z == 1:
        if not q:
            add([op], f"POP {RP2[p]}", 10, intel=True)
        elif p != 1:
            add(
                [op],
                ("RET", "", "JP (HL)", "LD SP,HL")[p],
                (10, 0, 4, 6)[p],
                intel=True,
            )
        else:
            add([op], "EXX", 4)
    elif z == 2:
        add([op], f"JP {CC[y]},nn", 10, intel=True)
    elif z == 3:
        if y in (1,):
            continue
        add(
            [op],
            (
                "JP nn",
                "",
                "OUT (n),A",
                "IN A,(n)",
                "EX (SP),HL",
                "EX DE,HL",
                "DI",
                "EI",
            )[y],
            (10, 0, 11, 11, 19, 4, 4, 4)[y],
            intel=True,
        )
    elif z == 4:
        add([op], f"CALL {CC[y]},nn", 10, 17, True)
    elif z == 5:
        if not q:
            add([op], f"PUSH {RP2[p]}", 11, intel=True)
        elif p == 0:
            add([op], "CALL nn", 17, intel=True)
    elif z == 6:
        add([op], ALU[y] + "n", 7, intel=True)
    else:
        add([op], f"RST {y*8:02X}H", 11, intel=True)

for op in range(256):
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    t = (
        (("RLC", "RRC", "RL", "RR", "SLA", "SRA", "SLL", "SRL")[y] + " " + R[z])
        if x == 0
        else f'{("", "BIT", "RES", "SET")[x]} {y},{R[z]}'
    )
    add(
        [0xCB, op],
        t,
        (12 if x == 1 else 15) if z == 6 else 8,
        undocumented=x == 0 and y == 6,
    )

for op in range(256):
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    p, q = y >> 1, y & 1
    if x == 1:
        if z == 0:
            add(
                [0xED, op],
                "IN (C)" if y == 6 else f"IN {R[y]},(C)",
                12,
                undocumented=y == 6,
            )
        elif z == 1:
            add([0xED, op], f"OUT (C),{0 if y==6 else R[y]}", 12, undocumented=y == 6)
        elif z == 2:
            add([0xED, op], f'{"ADC" if q else "SBC"} HL,{RP[p]}', 15)
        elif z == 3:
            add(
                [0xED, op],
                f"LD {RP[p]},(nn)" if q else f"LD (nn),{RP[p]}",
                20,
                undocumented=p == 2,
            )
        elif z == 4:
            add([0xED, op], "NEG", 8, undocumented=op != 0x44)
        elif z == 5:
            add(
                [0xED, op],
                "RETI" if op == 0x4D else "RETN",
                14,
                undocumented=op not in (0x45, 0x4D),
            )
        elif z == 6:
            add(
                [0xED, op],
                f"IM {(0,0,1,2,0,0,1,2)[y]}",
                8,
                undocumented=op not in (0x46, 0x56, 0x5E),
            )
        elif y < 6:
            add(
                [0xED, op],
                ("LD I,A", "LD R,A", "LD A,I", "LD A,R", "RRD", "RLD")[y],
                18 if y >= 4 else 9,
            )
    elif x == 2 and y >= 4 and z <= 3:
        add(
            [0xED, op],
            (
                ("LDI", "CPI", "INI", "OUTI"),
                ("LDD", "CPD", "IND", "OUTD"),
                ("LDIR", "CPIR", "INIR", "OTIR"),
                ("LDDR", "CPDR", "INDR", "OTDR"),
            )[y - 4][z],
            16,
            21 if y >= 6 else None,
        )

# Only effective index prefixes are catalogued. Ignored/repeated prefixes are
# decoded dynamically rather than generating an unbounded alias catalogue.
base = tuple(i for i in _items if len(i.opcode) == 1)
for prefix, index in ((0xDD, "IX"), (0xFD, "IY")):
    for i in base:
        if (
            i.text == "EX DE,HL"
            or "HL" not in i.operands
            and not any(
                r in i.operands.replace("HALT", "").replace("SP", "").split(",")
                for r in ("H", "L")
            )
        ):
            continue
        operands = i.operands
        memory = "(HL)" in operands
        if memory:
            operands = operands.replace("(HL)", f"({index}+d)")
        else:
            operands = ",".join(
                (
                    index
                    if r == "HL"
                    else index + "H" if r == "H" else index + "L" if r == "L" else r
                )
                for r in operands.split(",")
            )
            operands = operands.replace("(HL)", f"({index})")
        # JP (IX/IY) has no displacement.
        if i.mnemonic == "JP":
            operands = f"({index})"
            memory = False
        cycles = i.cycles + 4
        if memory:
            cycles = 23 if i.mnemonic in ("INC", "DEC") else 19
        _items.append(
            replace(
                i,
                opcode=bytes([prefix]) + i.opcode,
                operands=operands,
                byte_count=i.byte_count + 1 + int(memory),
                cycles=cycles,
                is_i8080=False,
                undocumented=not memory
                and (index + "H" in operands or index + "L" in operands),
            )
        )
    for op in range(256):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        t = (
            (
                ("RLC", "RRC", "RL", "RR", "SLA", "SRA", "SLL", "SRL")[y]
                + f" ({index}+d)"
            )
            if x == 0
            else f'{("", "BIT", "RES", "SET")[x]} {y},({index}+d)'
        )
        if x != 1 and z != 6:
            t += "," + R[z]
        m, _, operands = t.partition(" ")
        _items.append(
            Instruction(
                m,
                operands,
                bytes([prefix, 0xCB, op]),
                4,
                20 if x == 1 else 23,
                undocumented=z != 6 or x == 0 and y == 6,
                displacement_before_opcode=True,
            )
        )

INSTRUCTIONS = tuple(_items)
BY_OPCODE = {i.opcode: i for i in INSTRUCTIONS}
BY_MNEMONIC = defaultdict(list)
for i in INSTRUCTIONS:
    BY_MNEMONIC[i.mnemonic].append(i)


def validate():
    assert len(BY_OPCODE) == len(INSTRUCTIONS), "duplicate encoding"
    assert all(i.byte_count >= len(i.opcode) and i.cycles > 0 for i in INSTRUCTIONS)


@dataclass(frozen=True)
class Decoded:
    address: int
    data: bytes
    instruction: Instruction
    operands: str
    next_address: int

    @property
    def text(self):
        return self.instruction.mnemonic + (
            " " + self.operands if self.operands else ""
        )


def disassemble_one(read8, address):
    start = address & 65535
    pc = start
    data = []

    def fetch():
        nonlocal pc
        v = read8(pc) & 255
        pc = (pc + 1) & 65535
        data.append(v)
        return v

    op = fetch()
    prefix = None
    while op in (0xDD, 0xFD):
        prefix = op
        op = fetch()
        if len(data) > 65536:
            raise ValueError("prefix stream has no instruction")
    disp = None
    if op == 0xCB:
        if prefix is not None:
            disp = fetch()
            code = bytes([prefix, op, fetch()])
        else:
            code = bytes([op, fetch()])
    elif op == 0xED:
        code = bytes([op, fetch()])
    else:
        code = (
            bytes([prefix, op])
            if prefix is not None and bytes([prefix, op]) in BY_OPCODE
            else bytes([op])
        )
    i = BY_OPCODE.get(code)
    if i is None:
        # Undefined ED opcodes execute as two-byte NOPs on NMOS Z80.
        i = Instruction("NOP", "", code, len(code), 8, undocumented=True)
    operands = i.operands
    if "+d" in operands:
        if disp is None:
            disp = fetch()
        d = disp if disp < 128 else disp - 256
        operands = operands.replace("+d", f"{d:+d}")
    if "nn" in operands:
        value = fetch() | fetch() << 8
        operands = operands.replace("nn", f"${value:04X}")
    elif "n" in operands:
        operands = operands.replace("n", f"${fetch():02X}")
    if "e" in operands:
        d = fetch()
        target = (pc + (d if d < 128 else d - 256)) & 65535
        operands = operands.replace("e", f"${target:04X}")
    return Decoded(start, bytes(data), i, operands, pc)


def format_line(d):
    return f'{d.address:04X}  {d.data.hex(" ").upper():<17} {d.text}'
