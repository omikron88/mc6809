"""Motorola MC6809 and Hitachi HD6309 emulation core.

The core deliberately owns no memory. Instruction and data accesses go through
the host callbacks; internal/dummy cycles are counted without callback accesses.
Implements the documented 6809 and 6309 instruction sets. Undocumented silicon
opcodes, prefetch effects and electrical bus timing are outside this model.

Reference: Motorola 6809 and Hitachi 6309 Programming Reference,
Darren Atkinson (6x09 Instruction Sets). Division uses the published nominal
timing/overflow rules; undocumented silicon deviations are not modelled.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

Read = Callable[[int], int]
Write = Callable[[int, int], None]

# Condition-code bits
E, F, H, I, N, Z, V, C = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)


class IllegalInstruction(RuntimeError):
    """Raised when the CPU encounters an unsupported/illegal opcode."""

    def __init__(self, pc: int, opcode: int, page: int = 0):
        self.pc, self.opcode, self.page = pc, opcode, page
        prefix = f"{page:02X} " if page else ""
        super().__init__(f"illegal instruction {prefix}{opcode:02X} at {pc:04X}")


@dataclass
class Registers:
    """Public, mutable programmer-visible CPU state."""

    a: int = 0
    b: int = 0
    x: int = 0
    y: int = 0
    u: int = 0
    s: int = 0
    pc: int = 0
    dp: int = 0
    cc: int = I | F
    # HD6309 registers (harmless and accessible on an MC6809 instance).
    e: int = 0
    f: int = 0
    v: int = 0
    md: int = 0

    @property
    def d(self) -> int:
        return (self.a << 8) | self.b

    @d.setter
    def d(self, value: int) -> None:
        self.a, self.b = (value >> 8) & 0xFF, value & 0xFF

    @property
    def w(self) -> int:
        return (self.e << 8) | self.f

    @w.setter
    def w(self, value: int) -> None:
        self.e, self.f = (value >> 8) & 0xFF, value & 0xFF

    @property
    def q(self) -> int:
        return (self.d << 16) | self.w

    @q.setter
    def q(self, value: int) -> None:
        self.d, self.w = (value >> 16) & 0xFFFF, value & 0xFFFF


class CPU:
    """Instruction-level MC6809/HD6309 emulator, with cycle accounting.

    All instruction/data/stack accesses use read/write callbacks. Internal and
    dummy bus cycles are counted, but are NOT emitted as callback accesses.
    step() executes an instruction (TFM can be interrupted by a callback).
    IRQ/FIRQ are level-sensitive; nmi() supplies a latched edge after LDS/LEAS.
    HD6309 illegal instructions trap through FFF0 by default. Pass
    illegal_policy="raise" to use IllegalInstruction for debugger diagnostics.
    Timing follows the published 6x09 instruction tables; this is not a
    transistor-level or bus-cycle-exact model (notably division edge cases).
    """

    def __init__(self, read: Read, write: Write,
                 variant: Literal["6809", "6309"] = "6809", *,
                 illegal_policy: Literal["trap", "raise"] | None = None):
        if not callable(read) or not callable(write):
            raise TypeError("read and write must be callable")
        if variant not in ("6809", "6309"):
            raise ValueError("variant must be '6809' or '6309'")
        if illegal_policy not in (None, "trap", "raise"):
            raise ValueError("illegal_policy must be 'trap' or 'raise'")
        if variant == "6809" and illegal_policy == "trap":
            raise ValueError("6809 has no illegal-instruction trap")
        self.read, self.write, self.variant = read, write, variant
        self.illegal_policy = illegal_policy or ("trap" if variant == "6309" else "raise")
        self.r = Registers()
        self.cycles = 0
        self.waiting = self.syncing = False
        self._irq = self._firq = self._nmi = False
        self._nmi_armed = False
        self._start = self._page = self._op = 0

    @property
    def native(self) -> bool:
        return self.variant == "6309" and bool(self.r.md & 1)

    def rb(self, address: int) -> int:
        return self.read(address & 0xFFFF) & 0xFF

    def wb(self, address: int, value: int) -> None:
        self.write(address & 0xFFFF, value & 0xFF)

    def rw(self, address: int) -> int:
        return (self.rb(address) << 8) | self.rb(address + 1)

    def ww(self, address: int, value: int) -> None:
        self.wb(address, value >> 8)
        self.wb(address + 1, value)

    def reset(self) -> None:
        # V survives RESET on the 6309. Other unspecified registers start at 0.
        v = self.r.v if self.variant == "6309" else 0
        self.r = Registers(v=v)
        self.r.pc = self.rw(0xFFFE)
        self.waiting = self.syncing = False
        self._irq = self._firq = self._nmi = False
        self._nmi_armed = False
        self.cycles = 0

    def irq(self, active: bool = True) -> None:
        self._irq = bool(active)

    def firq(self, active: bool = True) -> None:
        self._firq = bool(active)

    def nmi(self) -> None:
        if self._nmi_armed:
            self._nmi = True

    def run(self, cycle_budget: int) -> int:
        """Run whole instructions until at least cycle_budget cycles elapse."""
        spent = 0
        while spent < cycle_budget:
            spent += self.step()
        return spent

    def _fetch8(self) -> int:
        value = self.rb(self.r.pc)
        self.r.pc = (self.r.pc + 1) & 0xFFFF
        return value

    def _fetch16(self) -> int:
        return (self._fetch8() << 8) | self._fetch8()

    @staticmethod
    def _signed(value: int, bits: int) -> int:
        value &= (1 << bits) - 1
        return value - (1 << bits) if value & (1 << (bits - 1)) else value

    @staticmethod
    def _sx8(value: int) -> int:
        return CPU._signed(value, 8)

    @staticmethod
    def _sx16(value: int) -> int:
        return CPU._signed(value, 16)

    def _push8(self, stack: str, value: int) -> None:
        address = (getattr(self.r, stack) - 1) & 0xFFFF
        setattr(self.r, stack, address)
        self.wb(address, value)

    def _push16(self, stack: str, value: int) -> None:
        self._push8(stack, value)
        self._push8(stack, value >> 8)

    def _pull8(self, stack: str) -> int:
        address = getattr(self.r, stack)
        value = self.rb(address)
        setattr(self.r, stack, (address + 1) & 0xFFFF)
        return value

    def _pull16(self, stack: str) -> int:
        return (self._pull8(stack) << 8) | self._pull8(stack)

    def _nz(self, value: int, bits: int, clear: int = N | Z | V) -> int:
        value &= (1 << bits) - 1
        self.r.cc &= ~clear
        if value == 0:
            self.r.cc |= Z
        if value & (1 << (bits - 1)):
            self.r.cc |= N
        return value

    def _logic(self, value: int, bits: int) -> int:
        return self._nz(value, bits)

    def _add(self, left: int, right: int, bits: int, carry: int = 0,
             half: bool = True) -> int:
        mask, sign = (1 << bits) - 1, 1 << (bits - 1)
        total = left + right + carry
        result = self._nz(total, bits, N | Z | V | C)
        if (~(left ^ right) & (left ^ result) & sign):
            self.r.cc |= V
        if total > mask:
            self.r.cc |= C
        if bits == 8 and half:
            self.r.cc &= ~H
            if (left & 15) + (right & 15) + carry > 15:
                self.r.cc |= H
        return result

    def _sub(self, left: int, right: int, bits: int, carry: int = 0) -> int:
        result = self._nz(left - right - carry, bits, N | Z | V | C)
        if (left ^ right) & (left ^ result) & (1 << (bits - 1)):
            self.r.cc |= V
        if left < right + carry:
            self.r.cc |= C
        return result

    def _illegal(self) -> None:
        raise IllegalInstruction(self._start, self._op, self._page)

    def _ea(self, mode: int) -> tuple[int, int]:
        """0=direct, 1=indexed, 2=extended; surcharge for indexed only."""
        if mode == 0:
            return ((self.r.dp << 8) | self._fetch8()) & 0xFFFF, 0
        if mode == 2:
            return self._fetch16(), 0
        if mode != 1:
            raise ValueError("invalid addressing mode")
        post = self._fetch8()
        reg = ("x", "y", "u", "s")[(post >> 5) & 3]
        base = getattr(self.r, reg)
        if not post & 0x80:
            offset = (post & 31) - (32 if post & 16 else 0)
            return (base + offset) & 0xFFFF, 1
        indirect, sub = bool(post & 16), post & 15
        native = self.native
        # W-based forms use encodings which are invalid on the MC6809.
        if self.variant == "6309" and post in (0x8F, 0x90, 0xAF, 0xB0, 0xCF, 0xD0, 0xEF, 0xF0):
            kind = (post >> 5) & 3
            ea = self.r.w
            if kind == 0:
                extra = 0
            elif kind == 1:
                ea += self._fetch16()
                extra = 2 if native else 6
            elif kind == 2:
                self.r.w += 2
                extra = 1 if native and not indirect else 3
            else:
                self.r.w -= 2
                ea = self.r.w
                extra = 1 if native and not indirect else 3
        elif sub in (0, 1, 2, 3):
            if indirect and sub in (0, 2):
                self._illegal()
            amount = 1 if sub in (0, 2) else 2
            ea = base
            if sub >= 2:
                ea = (base - amount) & 0xFFFF
            setattr(self.r, reg, ((base + amount) if sub < 2 else ea) & 0xFFFF)
            extra = amount + 1 - int(native and not indirect)
        elif sub == 4:
            ea, extra = base, 0
        elif sub in (5, 6, 7, 10):
            if sub in (7, 10) and self.variant != "6309":
                self._illegal()
            acc = {5: "b", 6: "a", 7: "e", 10: "f"}[sub]
            ea, extra = base + self._sx8(getattr(self.r, acc)), 1
        elif sub == 8:
            ea, extra = base + self._sx8(self._fetch8()), 1
        elif sub == 9:
            ea, extra = base + self._fetch16(), 3 if native else 4
        elif sub in (11, 14):
            if sub == 14 and self.variant != "6309":
                self._illegal()
            ea = base + (self.r.d if sub == 11 else self.r.w)
            extra = (2 if sub == 11 else 1) if native and not indirect else 4
        elif sub in (12, 13):
            offset = self._sx8(self._fetch8()) if sub == 12 else self._sx16(self._fetch16())
            ea = self.r.pc + offset
            extra = 1 if sub == 12 else (3 if native and not indirect else 5)
        elif sub == 15 and indirect:
            ea, extra = self._fetch16(), 2
        else:
            self._illegal()
        ea &= 0xFFFF
        if indirect:
            ea = self.rw(ea)
            extra += 3
        return ea, extra

    def _operand(self, mode: int, bits: int) -> tuple[int, int]:
        if mode == 3:
            return (self._fetch8() if bits == 8 else self._fetch16()), 0
        ea, extra = self._ea(mode)
        return (self.rb(ea) if bits == 8 else self.rw(ea)), extra

    def _frame(self, whole: bool) -> None:
        if not whole:
            self.r.cc &= ~E
            self._push16("s", self.r.pc)
            self._push8("s", self.r.cc)
            return
        self.r.cc |= E
        for name in ("pc", "u", "y", "x"):
            self._push16("s", getattr(self.r, name))
        self._push8("s", self.r.dp)
        if self.native:
            self._push8("s", self.r.f)
            self._push8("s", self.r.e)
        for name in ("b", "a", "cc"):
            self._push8("s", getattr(self.r, name))

    def _pending(self) -> int:
        if self._nmi:
            return 0xFFFC
        if self._firq and not self.r.cc & F:
            return 0xFFF6
        if self._irq and not self.r.cc & I:
            return 0xFFF8
        return 0

    def _interrupts(self) -> int:
        vector = self._pending()
        if not vector:
            return 0
        if vector == 0xFFFC:
            self._nmi = False
        if self.waiting:
            cycles = 7  # CWAI already stacked the entire state.
        else:
            whole = vector != 0xFFF6 or (self.variant == "6309" and bool(self.r.md & 2))
            self._frame(whole)
            cycles = 19 + 2 * int(self.native) if whole else 10
        self.r.cc |= I | (F if vector != 0xFFF8 else 0)
        self.r.pc = self.rw(vector)
        self.waiting = self.syncing = False
        return cycles

    def _trap(self, bit: int) -> int:
        self.r.md |= bit
        self._frame(True)
        self.r.pc = self.rw(0xFFF0)
        self.waiting = self.syncing = False
        return 20 + 2 * int(self.native)

    def step(self) -> int:
        if self.syncing and (self._irq or self._firq or self._nmi):
            self.syncing = False
        cycles = self._interrupts()
        if not cycles:
            if self.waiting or self.syncing:
                cycles = 1
            else:
                self._start = self.r.pc
                self._page = 0
                self._op = self._fetch8()
                if self._op in (0x10, 0x11):
                    self._page, self._op = self._op, self._fetch8()
                try:
                    cycles = self._execute(self._page, self._op, self._start)
                except IllegalInstruction:
                    if self.illegal_policy == "raise":
                        raise
                    cycles = self._trap(0x40)
        self.cycles += cycles
        return cycles

    def _condition(self, code: int) -> bool:
        n, z, v, c = (bool(self.r.cc & f) for f in (N, Z, V, C))
        return (True, False, not (c or z), c or z, not c, c, not z, z,
                not v, v, not n, n, n == v, n != v,
                not z and n == v, z or n != v)[code]

    def _execute(self, page: int, op: int, start: int) -> int:
        native = int(self.native)
        if (page == 0 and 0x20 <= op <= 0x2F) or (page == 0x10 and 0x21 <= op <= 0x2F):
            take = self._condition(op & 15)
            offset = self._sx8(self._fetch8()) if page == 0 else self._sx16(self._fetch16())
            if take:
                self.r.pc = (self.r.pc + offset) & 0xFFFF
            if page:
                return 5 + int(take and not native)
            return 3 - (native if op == 0x20 else 0)
        if self.variant == "6309":
            result = self._hd6309(op, page)
            if result is not None:
                return result
        if op == 0x3F and page in (0, 0x10, 0x11):
            self._frame(True)
            if page == 0:
                self.r.cc |= I | F
            self.r.pc = self.rw({0: 0xFFFA, 0x10: 0xFFF4, 0x11: 0xFFF2}[page])
            return 19 + int(bool(page)) + 2 * native
        if page == 0:
            if op == 0x12:
                return 2 - native
            if op == 0x13:
                self.syncing = True
                return 4 - native
            if op in (0x16, 0x17, 0x8D):
                offset = self._sx8(self._fetch8()) if op == 0x8D else self._sx16(self._fetch16())
                if op != 0x16:
                    self._push16("s", self.r.pc)
                self.r.pc = (self.r.pc + offset) & 0xFFFF
                return {0x16: 5-native, 0x17: 9-2*native, 0x8D: 7-native}[op]
            if op == 0x19:
                old = self.r.a
                correction = 6 if (old & 15) > 9 or self.r.cc & H else 0
                if old > 0x99 or self.r.cc & C:
                    correction |= 0x60
                self.r.a = self._nz(old + correction, 8)
                if old + correction > 255:
                    self.r.cc |= C
                return 2 - native
            if op in (0x1A, 0x1C):
                value = self._fetch8()
                self.r.cc = (self.r.cc | value) if op == 0x1A else (self.r.cc & value)
                return 3 - native
            if op == 0x1D:
                self.r.d = self._nz(self._sx8(self.r.b), 16, N | Z)
                return 2 - native
            if op in (0x1E, 0x1F):
                return self._exg_tfr(op == 0x1E)
            if 0x30 <= op <= 0x33:
                ea, extra = self._ea(1)
                name = ("x", "y", "s", "u")[op - 0x30]
                setattr(self.r, name, ea)
                if op < 0x32:
                    self.r.cc = (self.r.cc & ~Z) | (Z if ea == 0 else 0)
                if name == "s":
                    self._nmi_armed = True
                return 4 + extra
            if 0x34 <= op <= 0x37:
                return self._stack_op(op)
            if op == 0x39:
                self.r.pc = self._pull16("s")
                return 5 - native
            if op == 0x3A:
                self.r.x = (self.r.x + self.r.b) & 0xFFFF
                return 3 - 2 * native
            if op == 0x3B:
                self.r.cc = self._pull8("s")
                whole = bool(self.r.cc & E)
                if whole:
                    self.r.a, self.r.b = self._pull8("s"), self._pull8("s")
                    if native:
                        self.r.e, self.r.f = self._pull8("s"), self._pull8("s")
                    self.r.dp = self._pull8("s")
                    self.r.x, self.r.y, self.r.u = self._pull16("s"), self._pull16("s"), self._pull16("s")
                self.r.pc = self._pull16("s")
                return 15 + 2 * native if whole else 6
            if op == 0x3C:
                self.r.cc &= self._fetch8()
                self._frame(True)
                self.waiting = True
                return 20 + 2 * native
            if op == 0x3D:
                self.r.d = self.r.a * self.r.b
                self.r.cc = (self.r.cc & ~(Z | C)) | (Z if self.r.d == 0 else 0) | (C if self.r.b & 128 else 0)
                return 11 - native
            if op in (0x0E, 0x6E, 0x7E, 0x9D, 0xAD, 0xBD):
                mode = 0 if op in (0x0E, 0x9D) else 1 if op in (0x6E, 0xAD) else 2
                ea, extra = self._ea(mode)
                jsr = (op & 15) == 13
                if jsr:
                    self._push16("s", self.r.pc)
                self.r.pc = ea
                return (7 - native if jsr else 3 - (native if mode != 1 else 0)) + int(mode == 2) + extra
            if op < 0x10 or 0x40 <= op <= 0x7F:
                return self._unary(op, start)
        result = self._alu_matrix(page, op)
        if result is not None:
            return result
        self._illegal()

    def _unary_value(self, low: int, value: int, bits: int) -> int:
        mask, sign = (1 << bits) - 1, 1 << (bits - 1)
        oldcc = self.r.cc
        if low == 0:
            return self._sub(0, value, bits)
        if low == 3:
            result = self._nz(~value, bits)
            self.r.cc |= C
        elif low in (4, 6, 7):
            result = value >> 1
            if low == 6 and oldcc & C:
                result |= sign
            elif low == 7:
                result |= value & sign
            self._nz(result, bits, N | Z | C)
            self.r.cc |= C if value & 1 else 0
        elif low in (8, 9):
            result = ((value << 1) | (int(bool(oldcc & C)) if low == 9 else 0)) & mask
            self._nz(result, bits, N | Z | V | C)
            self.r.cc |= C if value & sign else 0
            if bool(self.r.cc & N) != bool(self.r.cc & C):
                self.r.cc |= V
        elif low in (10, 12):
            result = self._nz(value + (-1 if low == 10 else 1), bits)
            if value == (sign if low == 10 else sign - 1):
                self.r.cc |= V
        elif low == 13:
            result = self._nz(value, bits)
        elif low == 15:
            result = 0
            self.r.cc = (self.r.cc & ~(N | V | C)) | Z
        else:
            self._illegal()
        return result

    def _unary(self, op: int, start: int) -> int:
        low = op & 15
        if low not in (0, 3, 4, 6, 7, 8, 9, 10, 12, 13, 15):
            self._illegal()
        native = int(self.native)
        if 0x40 <= op <= 0x5F:
            reg = "a" if op < 0x50 else "b"
            result = self._unary_value(low, getattr(self.r, reg), 8)
            if low != 13:
                setattr(self.r, reg, result)
            return 2 - native
        mode = 0 if op < 0x10 else 1 if op < 0x70 else 2
        ea, extra = self._ea(mode)
        result = self._unary_value(low, self.rb(ea), 8)
        if low != 13:
            self.wb(ea, result)
        # TST saves an extra cycle in native mode; other indexed RMW do not.
        return 6 + int(mode == 2) + extra - native * (int(mode != 1) + int(low == 13))

    def _alu_matrix(self, page: int, op: int) -> int | None:
        if op < 0x80:
            return None
        group, low, bank = (op >> 4) & 3, op & 15, bool(op & 0x40)
        mode = 3 if group == 0 else group - 1
        reg, bits, action = "", 8, ""
        if page == 0:
            if low in (0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11):
                reg = "b" if bank else "a"
                action = {0:"sub", 1:"cmp", 2:"sbc", 4:"and", 5:"bit", 6:"ld", 7:"st", 8:"xor", 9:"adc", 10:"or", 11:"add"}[low]
            elif low == 3:
                reg, bits, action = "d", 16, "add" if bank else "sub"
            elif low == 12:
                reg, bits, action = ("d", 16, "ld") if bank else ("x", 16, "cmp")
            elif low == 13 and bank:
                reg, bits, action = "d", 16, "st"
            elif low in (14, 15):
                reg, bits, action = "u" if bank else "x", 16, "ld" if low == 14 else "st"
        elif page == 0x10:
            bits = 16
            if not bank:
                if low in (3, 12):
                    reg, action = "d" if low == 3 else "y", "cmp"
                elif low in (14, 15):
                    reg, action = "y", "ld" if low == 14 else "st"
                elif self.variant == "6309" and low in (0,1,2,4,5,6,7,8,9,10,11):
                    reg = "w" if low in (0,1,6,7,11) else "d"
                    action = {0:"sub",1:"cmp",2:"sbc",4:"and",5:"bit",6:"ld",7:"st",8:"xor",9:"adc",10:"or",11:"add"}[low]
            elif low in (14, 15):
                reg, action = "s", "ld" if low == 14 else "st"
        elif page == 0x11:
            if not bank and low in (3,12):
                reg, bits, action = "u" if low == 3 else "s", 16, "cmp"
            elif self.variant == "6309" and low in (0,1,6,7,11):
                reg = "f" if bank else "e"
                action = {0:"sub",1:"cmp",6:"ld",7:"st",11:"add"}[low]
        if not action or (action == "st" and mode == 3):
            return None
        if action == "st":
            ea, extra = self._ea(mode)
            value = self._logic(getattr(self.r, reg), bits)
            (self.wb if bits == 8 else self.ww)(ea, value)
        else:
            value, extra = self._operand(mode, bits)
            result = self._alu_value(action, getattr(self.r, reg), value, bits)
            if action not in ("cmp", "bit"):
                setattr(self.r, reg, result)
                if reg == "s" and action == "ld":
                    self._nmi_armed = True
        # Columns: immediate / direct / indexed / extended.
        prefix = int(bool(page))
        native = int(self.native)
        if bits == 8:
            cycles = (2, 4-native, 4, 5-native)[group] + prefix
        elif action in ("ld", "st"):
            cycles = (3, 5-native, 5, 6-native)[group] + prefix
        else:
            cycles = (4-native, 6-2*native, 6-native, 7-2*native)[group] + prefix
        return cycles + extra

    def _alu_value(self, action: str, left: int, right: int, bits: int,
                   half: bool = True) -> int:
        if action in ("sub", "cmp", "sbc"):
            return self._sub(left, right, bits, int(bool(self.r.cc & C)) if action == "sbc" else 0)
        if action in ("add", "adc"):
            return self._add(left, right, bits, int(bool(self.r.cc & C)) if action == "adc" else 0, half)
        if action in ("and", "bit"):
            return self._logic(left & right, bits)
        if action == "xor":
            return self._logic(left ^ right, bits)
        if action == "or":
            return self._logic(left | right, bits)
        return self._logic(right, bits)

    def _stack_op(self, op: int) -> int:
        mask = self._fetch8()
        stack = "s" if op in (0x34, 0x35) else "u"
        pull = op in (0x35, 0x37)
        fields = [("cc",1),("a",1),("b",1),("dp",1),("x",2),("y",2),("u" if stack == "s" else "s",2),("pc",2)]
        count = 0
        for bit in (range(8) if pull else range(7, -1, -1)):
            name, size = fields[bit]
            if mask & (1 << bit):
                if pull:
                    setattr(self.r, name, (self._pull8 if size == 1 else self._pull16)(stack))
                else:
                    (self._push8 if size == 1 else self._push16)(stack, getattr(self.r, name))
                count += size
        return 5 - int(self.native) + count

    def _reg(self, code: int) -> tuple[str | None, int]:
        table = {0:("d",16),1:("x",16),2:("y",16),3:("u",16),4:("s",16),5:("pc",16),8:("a",8),9:("b",8),10:("cc",8),11:("dp",8)}
        if self.variant == "6309":
            table.update({6:("w",16),7:("v",16),12:(None,8),13:(None,8),14:("e",8),15:("f",8)})
        if code not in table:
            self._illegal()
        return table[code]

    def _exg_tfr(self, exchange: bool) -> int:
        post = self._fetch8()
        codes = (post >> 4, post & 15)
        regs = [self._reg(code) for code in codes]
        values = []
        for name, size in regs:
            value = getattr(self.r, name) if name else 0
            if size == 8:
                if self.variant == "6309" or name in ("cc", "dp"):
                    value *= 0x101
                else:
                    value |= 0xFF00
            values.append(value)
        for index in ((1, 0) if exchange else (1,)):
            name, size = regs[index]
            value = values[1-index]
            if name is not None:
                if size == 8 and self.variant == "6309" and name in ("a", "e", "dp"):
                    value >>= 8
                setattr(self.r, name, value & ((1 << size) - 1))
        return (5 if self.native else 8) if exchange else (4 if self.native else 6)

    def _hd6309(self, op: int, page: int = 0x11) -> int | None:
        native = int(self.native)
        if page == 0:
            if op == 0xCD:
                self.r.q = self._logic((self._fetch16() << 16) | self._fetch16(), 32)
                return 5
            if op == 0x14:
                self.r.d = 0xFFFF if self.r.w & 0x8000 else 0
                self._nz(self.r.q, 32, N | Z)
                return 4
            if (op < 0x10 or 0x60 <= op <= 0x7F) and (op & 15) in (1,2,5,11):
                value = self._fetch8()
                mode = 0 if op < 0x10 else 1 if op < 0x70 else 2
                ea, extra = self._ea(mode)
                old = self.rb(ea)
                low = op & 15
                result = old | value if low == 1 else old ^ value if low == 5 else old & value
                result = self._logic(result, 8)
                if low != 11:
                    self.wb(ea, result)
                return (6,7,7)[mode] + extra
        elif page == 0x10:
            if 0x30 <= op <= 0x37:
                return self._register_alu(op)
            if 0x38 <= op <= 0x3B:
                stack = "s" if op < 0x3A else "u"
                if op & 1:
                    self.r.w = self._pull16(stack)
                else:
                    self._push16(stack, self.r.w)
                return 6
            valid_d = (0x40,0x43,0x44,0x46,0x47,0x48,0x49,0x4A,0x4C,0x4D,0x4F)
            valid_w = (0x53,0x54,0x56,0x59,0x5A,0x5C,0x5D,0x5F)
            if op in valid_d + valid_w:
                reg = "d" if op < 0x50 else "w"
                result = self._unary_value(op & 15, getattr(self.r, reg), 16)
                if op & 15 != 13:
                    setattr(self.r, reg, result)
                return 3 - native
            if op in (0xDC,0xDD,0xEC,0xED,0xFC,0xFD):
                mode = ((op >> 4) & 3) - 1
                ea, extra = self._ea(mode)
                if op & 1:
                    value = self._logic(self.r.q, 32)
                    self.ww(ea, value >> 16)
                    self.ww(ea + 2, value)
                else:
                    self.r.q = self._logic((self.rw(ea) << 16) | self.rw(ea + 2), 32)
                return (8-native,8,9-native)[mode] + extra
        elif page == 0x11:
            if 0x30 <= op <= 0x37:
                return self._bit_op(op)
            if 0x38 <= op <= 0x3B:
                return self._tfm(op)
            if op == 0x3C:
                mask = self._fetch8() & 0xC0
                self.r.cc = (self.r.cc & ~Z) | (Z if not (self.r.md & mask) else 0)
                self.r.md &= ~mask
                return 4
            if op == 0x3D:
                self.r.md = (self.r.md & 0xFC) | (self._fetch8() & 3)
                return 5
            if op in (0x43,0x4A,0x4C,0x4D,0x4F,0x53,0x5A,0x5C,0x5D,0x5F):
                reg = "e" if op < 0x50 else "f"
                result = self._unary_value(op & 15, getattr(self.r, reg), 8)
                if op & 15 != 13:
                    setattr(self.r, reg, result)
                return 3 - native
            if 0x80 <= op <= 0xBF and (op & 15) in (13,14,15):
                group = (op >> 4) & 3
                mode = 3 if group == 0 else group - 1
                low = op & 15
                value, extra = self._operand(mode, 8 if low == 13 else 16)
                surcharge = (0,2-native,2,3-native)[group] + extra
                if low == 15:
                    self.r.q = self._nz(self._sx16(self.r.d) * self._sx16(value), 32, N | Z)
                    return 28 + surcharge
                return self._divide(value, 8 if low == 13 else 16) + surcharge
        return None

    def _register_alu(self, op: int) -> int:
        post = self._fetch8()
        source, sbits = self._reg(post >> 4)
        dest, bits = self._reg(post & 15)
        left = getattr(self.r, dest) if dest else 0
        right = getattr(self.r, source) if source else 0
        if bits == 16 and sbits == 8:
            if source in ("a", "b"):
                right = self.r.d
            elif source in ("e", "f"):
                right = self.r.w
            elif source == "dp":
                right <<= 8
        right &= (1 << bits) - 1
        action = ("add","adc","sub","sbc","and","or","xor","cmp")[op - 0x30]
        result = self._alu_value(action, left, right, bits, half=False)
        if action != "cmp" and dest:
            if dest == "cc":
                # Hardware writes the result between clearing and setting flags.
                mask = N | Z | V | (C if op <= 0x33 else 0)
                flags = self.r.cc & mask
                self.r.cc = result | flags
            else:
                setattr(self.r, dest, result)
        return 4

    def _bit_op(self, op: int) -> int:
        post = self._fetch8()
        code = post >> 6
        if code == 3:
            self._illegal()
        reg = ("cc", "a", "b")[code]
        ea, _ = self._ea(0)
        memory = self.rb(ea)
        value = getattr(self.r, reg)
        source_bit, dest_bit = (post >> 3) & 7, post & 7
        if op == 0x37:
            result = (memory & ~(1 << dest_bit)) | (((value >> source_bit) & 1) << dest_bit)
            self.wb(ea, result)
        else:
            source, dest = (memory >> source_bit) & 1, (value >> dest_bit) & 1
            result = (dest & source, dest & (source ^ 1), dest | source,
                      dest | (source ^ 1), dest ^ source, dest ^ (source ^ 1), source)[op-0x30]
            setattr(self.r, reg, (value & ~(1 << dest_bit)) | (result << dest_bit))
        return (8 if op == 0x37 else 7) - int(self.native)

    def _tfm(self, op: int) -> int:
        post = self._fetch8()
        src, dst = post >> 4, post & 15
        if src > 4 or dst > 4:
            self._illegal()
        src, dst = ("d","x","y","u","s")[src], ("d","x","y","u","s")[dst]
        source_delta, dest_delta = ((1,1),(-1,-1),(1,0),(0,1))[op-0x38]
        cycles = 6
        while self.r.w:
            value = self.rb(getattr(self.r, src))
            # An interrupt can be asserted by a memory-mapped device callback.
            if self._pending():
                self.r.pc = self._start
                return cycles + 1 + self._interrupts()
            if source_delta:
                setattr(self.r, src, (getattr(self.r, src) + source_delta) & 0xFFFF)
            self.wb(getattr(self.r, dst), value)
            if dest_delta:
                setattr(self.r, dst, (getattr(self.r, dst) + dest_delta) & 0xFFFF)
            self.r.w -= 1
            cycles += 3
        return cycles

    def _divide(self, divisor: int, bits: int) -> int:
        """Published signed DIVD/DIVQ semantics and nominal table timing."""
        cycles = 25 if bits == 8 else 34
        divisor = self._signed(divisor, bits)
        if divisor == 0:
            return cycles + self._trap(0x80)
        dividend = self._signed(self.r.d if bits == 8 else self.r.q, bits * 2)
        quotient = abs(dividend) // abs(divisor)
        if (dividend < 0) != (divisor < 0):
            quotient = -quotient
        remainder = dividend - quotient * divisor
        # A quotient outside the unsigned magnitude range aborts the operation.
        if abs(quotient) > (1 << bits) - 1:
            self.r.cc = (self.r.cc & ~(N | Z | V | C)) | V
            return cycles - (13 if bits == 8 else 21)
        result = self._nz(quotient, bits, N | Z | V | C)
        if result & 1:
            self.r.cc |= C
        overflow = not (-(1 << (bits-1)) <= quotient < (1 << (bits-1)))
        if overflow:
            self.r.cc |= V
            if bits == 8:
                cycles -= 1
        if bits == 8:
            self.r.a, self.r.b = remainder & 255, result
        else:
            self.r.d, self.r.w = remainder & 0xFFFF, result
        return cycles


class MC6809(CPU):
    def __init__(self, read: Read, write: Write, **kwargs):
        super().__init__(read, write, variant="6809", **kwargs)


class HD6309(CPU):
    def __init__(self, read: Read, write: Write, **kwargs):
        super().__init__(read, write, variant="6309", **kwargs)
