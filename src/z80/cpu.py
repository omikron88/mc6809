"""Callback-driven NMOS Z80, instruction timing (not pin-level emulation)."""

from dataclasses import dataclass
from .instructions import BY_OPCODE

S, Z, Y, H, X, PV, N, C = 128, 64, 32, 16, 8, 4, 2, 1


def parity(v):
    return (v & 255).bit_count() % 2 == 0


def szp(v):
    return (v & (S | Y | X)) | (Z if v == 0 else 0) | (PV if parity(v) else 0)


def signed(v):
    return v if v < 128 else v - 256


@dataclass
class Registers:
    a: int = 0
    f: int = 0
    b: int = 0
    c: int = 0
    d: int = 0
    e: int = 0
    h: int = 0
    l: int = 0
    a_alt: int = 0
    f_alt: int = 0
    b_alt: int = 0
    c_alt: int = 0
    d_alt: int = 0
    e_alt: int = 0
    h_alt: int = 0
    l_alt: int = 0
    ix: int = 0
    iy: int = 0
    sp: int = 65535
    pc: int = 0
    i: int = 0
    r: int = 0


def pair(hi, lo):
    return property(
        lambda s: (getattr(s, hi) << 8) | getattr(s, lo),
        lambda s, v: (setattr(s, hi, (v >> 8) & 255), setattr(s, lo, v & 255)),
    )


for name, hi, lo in [
    ("af", "a", "f"),
    ("bc", "b", "c"),
    ("de", "d", "e"),
    ("hl", "h", "l"),
]:
    setattr(Registers, name, pair(hi, lo))
    setattr(Registers, name + "_alt", pair(hi + "_alt", lo + "_alt"))


class Z80:
    def __init__(
        self, read, write, *, fetch=None, intack=None, input_port=None, output_port=None
    ):
        self.read = read
        self.write = write
        self.fetch = read if fetch is None else fetch
        self.intack = (lambda: self._bus) if intack is None else intack
        self.input_port = input_port or (lambda port: 255)
        self.output_port = output_port or (lambda port, value: None)
        self.reset()

    def reset(self):
        self.r = Registers()
        self.cycles = 0
        self.halted = False
        self.iff1 = self.iff2 = False
        self.im = 0
        self._irq = False
        self._nmi = False
        self._ei = 0
        self._bus = 255

    def irq(self, active=True, data=255):
        self._irq = bool(active)
        self._bus = data & 255

    def nmi(self):
        self._nmi = True

    def _rd(self, a):
        return self.read(a & 65535) & 255

    def _wr(self, a, v):
        self.write(a & 65535, v & 255)

    def _word(self, a):
        return self._rd(a) | (self._rd(a + 1) << 8)

    def _putword(self, a, v):
        self._wr(a, v)
        self._wr(a + 1, v >> 8)

    def _fetch(self):
        v = self._rd(self.r.pc)
        self.r.pc = (self.r.pc + 1) & 65535
        return v

    def _m1(self):
        self.r.r = (self.r.r & 128) | ((self.r.r + 1) & 127)
        v = self.fetch(self.r.pc & 65535) & 255
        self.r.pc = (self.r.pc + 1) & 65535
        return v

    def _imm16(self):
        return self._fetch() | self._fetch() << 8

    def _push(self, v):
        self.r.sp = (self.r.sp - 1) & 65535
        self._wr(self.r.sp, v >> 8)
        self.r.sp = (self.r.sp - 1) & 65535
        self._wr(self.r.sp, v)

    def _pop(self):
        v = self._word(self.r.sp)
        self.r.sp = (self.r.sp + 2) & 65535
        return v

    def _pair(self, p, index=None, af=False):
        return ("bc", "de", index or "hl", "af" if af else "sp")[p]

    def _get(self, z, index=None, address=None, plain=False):
        if z == 6:
            return self._rd(address if address is not None else self.r.hl)
        if index and z in (4, 5) and not plain:
            return (getattr(self.r, index) >> (8 if z == 4 else 0)) & 255
        return getattr(self.r, ("b", "c", "d", "e", "h", "l", "", "a")[z])

    def _set(self, z, v, index=None, address=None, plain=False):
        v &= 255
        if z == 6:
            self._wr(address if address is not None else self.r.hl, v)
        elif index and z in (4, 5) and not plain:
            old = getattr(self.r, index)
            setattr(
                self.r,
                index,
                ((v << 8) | (old & 255)) if z == 4 else ((old & 65280) | v),
            )
        else:
            setattr(self.r, ("b", "c", "d", "e", "h", "l", "", "a")[z], v)

    def _condition(self, y):
        f = self.r.f
        return (
            not f & Z,
            bool(f & Z),
            not f & C,
            bool(f & C),
            not f & PV,
            bool(f & PV),
            not f & S,
            bool(f & S),
        )[y]

    def _alu(self, y, v):
        a = self.r.a
        carry = int(bool(self.r.f & C)) if y in (1, 3) else 0
        if y in (0, 1, 2, 3, 7):
            sub = y in (2, 3, 7)
            total = a - v - carry if sub else a + v + carry
            out = total & 255
            overflow = (
                ((a ^ v) & (a ^ out) & 128) if sub else (~(a ^ v) & (a ^ out) & 128)
            )
            self.r.f = (
                (out & (S | Y | X))
                | (Z if out == 0 else 0)
                | (H if (a ^ v ^ out) & 16 else 0)
                | (PV if overflow else 0)
                | (N if sub else 0)
                | (C if total < 0 or total > 255 else 0)
            )
            if y == 7:
                self.r.f = (self.r.f & ~(Y | X)) | (v & (Y | X))
            else:
                self.r.a = out
        else:
            out = (a & v) if y == 4 else (a ^ v) if y == 5 else (a | v)
            self.r.a = out
            self.r.f = szp(out) | (H if y == 4 else 0)

    def _inc(self, v, dec=False):
        out = (v + (-1 if dec else 1)) & 255
        self.r.f = (
            (self.r.f & C)
            | (out & (S | Y | X))
            | (Z if out == 0 else 0)
            | (H if (v ^ out) & 16 else 0)
            | (PV if v == (128 if dec else 127) else 0)
            | (N if dec else 0)
        )
        return out

    def _rotate(self, y, v):
        c = int(bool(self.r.f & C))
        if y == 0:
            out = (v << 1) | (v >> 7)
            carry = v >> 7
        elif y == 1:
            out = (v >> 1) | (v << 7)
            carry = v & 1
        elif y == 2:
            out = (v << 1) | c
            carry = v >> 7
        elif y == 3:
            out = (v >> 1) | (c << 7)
            carry = v & 1
        elif y == 4:
            out = v << 1
            carry = v >> 7
        elif y == 5:
            out = (v >> 1) | (v & 128)
            carry = v & 1
        elif y == 6:
            out = (v << 1) | 1
            carry = v >> 7
        else:
            out = v >> 1
            carry = v & 1
        out &= 255
        self.r.f = szp(out) | carry
        return out

    def _cb(self, op, index=None, address=None):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        v = self._rd(address) if index else self._get(z)
        if x == 1:
            bits = (address >> 8) if index else v
            self.r.f = (
                (self.r.f & C)
                | H
                | (bits & (Y | X))
                | (Z | PV if not v & (1 << y) else 0)
                | (S if y == 7 and v & 128 else 0)
            )
        else:
            out = (
                self._rotate(y, v)
                if x == 0
                else v & ~(1 << y) if x == 2 else v | (1 << y)
            )
            if index:
                self._wr(address, out)
                if z != 6:
                    self._set(z, out)
            else:
                self._set(z, out)

    def _ed(self, op):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        r = self.r
        repeat = False
        if x == 1:
            if z == 0:
                v = self.input_port(r.bc) & 255
                if y != 6:
                    self._set(y, v)
                r.f = (r.f & C) | szp(v)
            elif z == 1:
                self.output_port(r.bc, self._get(y) if y != 6 else 0)
            elif z == 2:
                a = r.hl
                b = getattr(r, self._pair(p))
                c = int(bool(r.f & C))
                total = a + b + c if q else a - b - c
                out = total & 65535
                overflow = (
                    (~(a ^ b) & (a ^ out) & 32768)
                    if q
                    else ((a ^ b) & (a ^ out) & 32768)
                )
                r.f = (
                    ((out >> 8) & (S | Y | X))
                    | (Z if not out else 0)
                    | (H if (a ^ b ^ out) & 4096 else 0)
                    | (PV if overflow else 0)
                    | (0 if q else N)
                    | (C if total < 0 or total > 65535 else 0)
                )
                r.hl = out
            elif z == 3:
                addr = self._imm16()
                name = self._pair(p)
                if q:
                    setattr(r, name, self._word(addr))
                else:
                    self._putword(addr, getattr(r, name))
            elif z == 4:
                v = r.a
                r.a = 0
                self._alu(2, v)
            elif z == 5:
                r.pc = self._pop()
                self.iff1 = self.iff2
            elif z == 6:
                self.im = (0, 0, 1, 2, 0, 0, 1, 2)[y]
            elif y < 4:
                if y == 0:
                    r.i = r.a
                elif y == 1:
                    r.r = r.a
                else:
                    r.a = r.i if y == 2 else r.r
                    r.f = (r.f & C) | (szp(r.a) & ~PV) | (PV if self.iff2 else 0)
            elif y in (4, 5):
                v = self._rd(r.hl)
                a = r.a
                if y == 4:
                    self._wr(r.hl, ((a & 15) << 4) | (v >> 4))
                    r.a = (a & 240) | (v & 15)
                else:
                    self._wr(r.hl, ((v << 4) & 240) | (a & 15))
                    r.a = (a & 240) | (v >> 4)
                r.f = (r.f & C) | szp(r.a)
        elif x == 2 and y >= 4 and z <= 3:
            delta = -1 if y & 1 else 1
            if z == 0:
                v = self._rd(r.hl)
                self._wr(r.de, v)
                r.hl = (r.hl + delta) & 65535
                r.de = (r.de + delta) & 65535
                r.bc = (r.bc - 1) & 65535
                t = (r.a + v) & 255
                r.f = (
                    (r.f & (S | Z | C)) | (PV if r.bc else 0) | (t & X) | ((t & 2) << 4)
                )
                repeat = r.bc != 0
            elif z == 1:
                v = self._rd(r.hl)
                out = (r.a - v) & 255
                half = bool((r.a ^ v ^ out) & 16)
                r.hl = (r.hl + delta) & 65535
                r.bc = (r.bc - 1) & 65535
                t = (out - int(half)) & 255
                r.f = (
                    (r.f & C)
                    | (out & S)
                    | (Z if not out else 0)
                    | (H if half else 0)
                    | N
                    | (PV if r.bc else 0)
                    | (t & X)
                    | ((t & 2) << 4)
                )
                repeat = bool(r.bc and out)
            else:
                if z == 2:
                    v = self.input_port(r.bc) & 255
                    self._wr(r.hl, v)
                else:
                    v = self._rd(r.hl)
                r.b = (r.b - 1) & 255
                r.hl = (r.hl + delta) & 65535
                if z == 3:
                    self.output_port(r.bc, v)
                t = v + (((r.c + delta) & 255) if z == 2 else r.l)
                r.f = (
                    (r.b & (S | Y | X))
                    | (Z if not r.b else 0)
                    | (N if v & 128 else 0)
                    | (H | C if t > 255 else 0)
                    | (PV if parity((t & 7) ^ r.b) else 0)
                )
                repeat = r.b != 0
            if y >= 6 and repeat:
                r.pc = (r.pc - 2) & 65535
                return True
        return False

    def _base(self, op, index=None):
        x, y, z = op >> 6, (op >> 3) & 7, op & 7
        p, q = y >> 1, y & 1
        r = self.r
        addr = None
        memory = index and (
            (x == 0 and z in (4, 5, 6) and y == 6)
            or (x == 1 and op != 0x76 and 6 in (y, z))
            or (x == 2 and z == 6)
        )
        if memory:
            addr = (getattr(r, index) + signed(self._fetch())) & 65535
        name = self._pair(p, index)
        if x == 0:
            if z == 0:
                if y == 1:
                    r.af, r.af_alt = r.af_alt, r.af
                elif y >= 2:
                    d = signed(self._fetch())
                    take = True
                    if y == 2:
                        r.b = (r.b - 1) & 255
                        take = r.b != 0
                    elif y >= 4:
                        take = self._condition(y - 4)
                    if take:
                        r.pc = (r.pc + d) & 65535
                    return take
            elif z == 1:
                if not q:
                    setattr(r, name, self._imm16())
                else:
                    target = index or "hl"
                    a = getattr(r, target)
                    b = getattr(r, name)
                    out = a + b
                    r.f = (
                        (r.f & (S | Z | PV))
                        | ((out >> 8) & (Y | X))
                        | (H if (a ^ b ^ out) & 4096 else 0)
                        | (C if out > 65535 else 0)
                    )
                    setattr(r, target, out & 65535)
            elif z == 2:
                if p < 2:
                    a = getattr(r, ("bc", "de")[p])
                else:
                    a = self._imm16()
                if p == 2:
                    if q:
                        setattr(r, index or "hl", self._word(a))
                    else:
                        self._putword(a, getattr(r, index or "hl"))
                elif q:
                    r.a = self._rd(a)
                else:
                    self._wr(a, r.a)
            elif z == 3:
                setattr(r, name, (getattr(r, name) + (-1 if q else 1)) & 65535)
            elif z in (4, 5):
                self._set(y, self._inc(self._get(y, index, addr), z == 5), index, addr)
            elif z == 6:
                self._set(y, self._fetch(), index, addr)
            else:
                a = r.a
                f = r.f
                if y < 4:
                    r.a = self._rotate(y, a)
                    r.f = (f & (S | Z | PV)) | (r.a & (Y | X)) | (r.f & C)
                elif y == 4:
                    adjustment = 0
                    carry = bool(f & C)
                    if f & H or not f & N and (a & 15) > 9:
                        adjustment |= 6
                    if carry or not f & N and a > 0x99:
                        adjustment |= 0x60
                        carry = True
                    r.a = (a - adjustment if f & N else a + adjustment) & 255
                    r.f = szp(r.a) | (f & N) | (H if (a ^ r.a) & 16 else 0) | int(carry)
                elif y == 5:
                    r.a ^= 255
                    r.f = (f & (S | Z | PV | C)) | H | N | (r.a & (Y | X))
                elif y == 6:
                    r.f = (f & (S | Z | PV)) | (a & (Y | X)) | C
                else:
                    r.f = (f & (S | Z | PV)) | (a & (Y | X)) | (H if f & C else C)
        elif x == 1:
            if op == 0x76:
                self.halted = True
            else:
                self._set(
                    y,
                    self._get(z, index, addr, bool(memory)),
                    index,
                    addr,
                    bool(memory),
                )
        elif x == 2:
            self._alu(y, self._get(z, index, addr))
        elif z == 0:
            take = self._condition(y)
            if take:
                r.pc = self._pop()
            return take
        elif z == 1:
            if not q:
                setattr(r, self._pair(p, index, True), self._pop())
            elif p == 0:
                r.pc = self._pop()
            elif p == 1:
                for pairname in ("bc", "de", "hl"):
                    a = getattr(r, pairname)
                    setattr(r, pairname, getattr(r, pairname + "_alt"))
                    setattr(r, pairname + "_alt", a)
            elif p == 2:
                r.pc = getattr(r, index or "hl")
            else:
                r.sp = getattr(r, index or "hl")
        elif z == 2:
            a = self._imm16()
            if self._condition(y):
                r.pc = a
        elif z == 3:
            if y == 0:
                r.pc = self._imm16()
            elif y in (2, 3):
                port = (r.a << 8) | self._fetch()
                if y == 2:
                    self.output_port(port, r.a)
                else:
                    r.a = self.input_port(port) & 255
            elif y == 4:
                a = getattr(r, index or "hl")
                v = self._word(r.sp)
                self._putword(r.sp, a)
                setattr(r, index or "hl", v)
            elif y == 5:
                r.de, r.hl = r.hl, r.de
            elif y == 6:
                self.iff1 = self.iff2 = False
            elif y == 7:
                self.iff1 = self.iff2 = True
                self._ei = 2
        elif z == 4:
            a = self._imm16()
            take = self._condition(y)
            if take:
                self._push(r.pc)
                r.pc = a
            return take
        elif z == 5:
            if not q:
                self._push(getattr(r, self._pair(p, index, True)))
            elif p == 0:
                a = self._imm16()
                self._push(r.pc)
                r.pc = a
        elif z == 6:
            self._alu(y, self._fetch())
        else:
            self._push(r.pc)
            r.pc = y * 8
        return False

    def step(self):
        r = self.r
        if self._nmi:
            self._nmi = False
            self.halted = False
            self.iff2 = self.iff1
            self.iff1 = False
            r.r = (r.r & 128) | ((r.r + 1) & 127)
            self.fetch(r.pc & 65535)
            self._push(r.pc)
            r.pc = 0x66
            t = 11
        elif self._irq and self.iff1 and not self._ei:
            self.halted = False
            self.iff1 = self.iff2 = False
            r.r = (r.r & 128) | ((r.r + 1) & 127)
            bus = self.intack() & 255
            if self.im == 0:
                t = self._execute(bus) + 2
            else:
                self._push(r.pc)
                r.pc = self._word((r.i << 8) | bus) if self.im == 2 else 0x38
                t = 19 if self.im == 2 else 13
        elif self.halted:
            self.fetch(r.pc & 65535)
            r.r = (r.r & 128) | ((r.r + 1) & 127)
            t = 4
        else:
            t = self._execute(self._m1())
        self.cycles += t
        return t

    def _execute(self, op):
        r = self.r
        prefix = None
        count = 0
        while op in (0xDD, 0xFD):
            prefix = op
            count += 1
            if count > 65536:
                raise ValueError("prefix stream has no instruction")
            op = self._m1()
        index = {0xDD: "ix", 0xFD: "iy"}.get(prefix)
        if op == 0xCB:
            if index:
                address = (getattr(r, index) + signed(self._fetch())) & 65535
                sub = self._fetch()
                key = bytes([prefix, op, sub])
                self._cb(sub, index, address)
            else:
                sub = self._m1()
                key = bytes([op, sub])
                self._cb(sub)
            t = BY_OPCODE[key].cycles + max(0, count - 1) * 4
        elif op == 0xED:
            sub = self._m1()
            key = bytes([op, sub])
            take = self._ed(sub)
            i = BY_OPCODE.get(key)
            t = ((i.cycles_taken if take else i.cycles) if i else 8) + count * 4
        else:
            key = (
                bytes([prefix, op])
                if prefix and bytes([prefix, op]) in BY_OPCODE
                else bytes([op])
            )
            i = BY_OPCODE[key]
            effective = index if len(key) == 2 else None
            take = self._base(op, effective)
            t = (i.cycles_taken if take and i.cycles_taken else i.cycles) + 4 * (
                count - (1 if effective else 0)
            )
        if self._ei:
            self._ei -= 1
        return t

    def run(self, budget):
        if budget < 0:
            raise ValueError("negative cycle budget")
        start = self.cycles
        while self.cycles - start < budget:
            self.step()
        return self.cycles - start


CPU = Z80
