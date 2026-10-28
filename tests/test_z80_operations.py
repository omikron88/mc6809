"""Independent expected results for additional architectural operations."""

import unittest
from z80 import Z80, Assembler, disassemble_one
from z80.cpu import S, Z, H, PV, N, C


class Operations(unittest.TestCase):
    def make(self, code):
        mem = bytearray(65536)
        mem[: len(code)] = bytes.fromhex(code)
        return Z80(mem.__getitem__, mem.__setitem__), mem

    def test_decimal_adjust(self):
        for a, b in ((9, 1), (0x99, 1), (0x48, 0x52), (0x15, 0x27)):
            cpu, _ = self.make("80 27")
            cpu.r.a = a
            cpu.r.b = b
            cpu.step()
            cpu.step()
            decimal = lambda v: 10 * (v >> 4) + (v & 15)
            total = decimal(a) + decimal(b)
            out = total % 100
            self.assertEqual(cpu.r.a, (out // 10) * 16 + out % 10)
            self.assertEqual(bool(cpu.r.f & C), total >= 100)
        cpu, _ = self.make("90 27")
        cpu.r.a = 0x10
        cpu.r.b = 1
        cpu.step()
        cpu.step()
        self.assertEqual(cpu.r.a, 9)
        self.assertTrue(cpu.r.f & N)

    def test_rotate_bit_and_set(self):
        cpu, _ = self.make("cb 10 cb 78 cb c0 cb 80")
        cpu.r.b = 0x80
        cpu.r.f = C
        cpu.step()
        self.assertEqual(cpu.r.b, 1)
        self.assertEqual(cpu.r.f, C)
        cpu.step()
        self.assertEqual(cpu.r.f, H | Z | PV | C)
        cpu.step()
        self.assertEqual(cpu.r.b, 1)
        cpu.step()
        self.assertEqual(cpu.r.b, 0)

    def test_alternate_banks(self):
        cpu, _ = self.make("08 d9")
        cpu.r.af = 0x1234
        cpu.r.af_alt = 0xABCD
        cpu.r.bc = 0x1122
        cpu.r.bc_alt = 0x3344
        cpu.step()
        self.assertEqual(cpu.r.af, 0xABCD)
        self.assertEqual(cpu.r.af_alt, 0x1234)
        cpu.step()
        self.assertEqual(cpu.r.bc, 0x3344)
        self.assertEqual(cpu.r.bc_alt, 0x1122)

    def test_word_arithmetic(self):
        cpu, _ = self.make("ed 4a ed 42")
        cpu.r.hl = 0x7FFF
        cpu.r.bc = 0
        cpu.r.f = C
        cpu.step()
        self.assertEqual(cpu.r.hl, 0x8000)
        self.assertEqual(cpu.r.f, S | H | PV)
        cpu.r.bc = 1
        cpu.step()
        self.assertEqual(cpu.r.hl, 0x7FFF)
        self.assertEqual(cpu.r.f, 0x28 | H | PV | N)

    def test_nibble_rotates(self):
        cpu, mem = self.make("ed 67 ed 6f")
        cpu.r.hl = 0x1000
        cpu.r.a = 0x12
        mem[0x1000] = 0x34
        cpu.step()
        self.assertEqual((cpu.r.a, mem[0x1000]), (0x14, 0x23))
        cpu.step()
        self.assertEqual((cpu.r.a, mem[0x1000]), (0x12, 0x34))

    def test_cpir(self):
        cpu, mem = self.make("ed b1")
        cpu.r.a = 2
        cpu.r.bc = 3
        cpu.r.hl = 0x1000
        mem[0x1000:0x1003] = bytes([1, 2, 3])
        self.assertEqual(cpu.step(), 21)
        self.assertEqual(cpu.step(), 16)
        self.assertEqual(cpu.r.bc, 1)
        self.assertEqual(cpu.r.hl, 0x1002)
        self.assertTrue(cpu.r.f & Z)

    def test_inir_and_otdr(self):
        cpu, mem = self.make("ed b2 ed bb")
        ports = []
        cpu.input_port = lambda p: ports.append(p) or (p >> 8)
        cpu.r.bc = 0x0210
        cpu.r.hl = 0x1000
        self.assertEqual(cpu.step(), 21)
        self.assertEqual(cpu.step(), 16)
        self.assertEqual(ports, [0x210, 0x110])
        self.assertEqual(mem[0x1000:0x1002], bytes([2, 1]))
        events = []
        cpu.output_port = lambda p, v: events.append((p, v))
        cpu.r.bc = 0x0210
        cpu.r.hl = 0x1001
        cpu.step()
        cpu.step()
        self.assertEqual(events, [(0x110, 1), (0x10, 2)])

    def test_im0_injected_call(self):
        cpu, mem = self.make("34 12")
        cpu.iff1 = True
        cpu.irq(data=0xCD)
        cpu.r.sp = 0x8000
        self.assertEqual(cpu.step(), 19)
        self.assertEqual(cpu.r.pc, 0x1234)
        self.assertEqual(mem[0x7FFE:0x8000], bytes([2, 0]))

    def test_im2(self):
        cpu, mem = self.make("00")
        cpu.im = 2
        cpu.iff1 = True
        cpu.r.i = 0x80
        mem[0x8010:0x8012] = bytes([0x34, 0x12])
        cpu.irq(data=0x10)
        self.assertEqual(cpu.step(), 19)
        self.assertEqual(cpu.r.pc, 0x1234)

    def test_negative_index_and_refresh(self):
        cpu, mem = self.make("fd 66 fe fd 74 ff fd cb ff 46")
        cpu.r.iy = 0x1000
        mem[0xFFE] = 0x55
        cpu.step()
        self.assertEqual(cpu.r.h, 0x55)
        self.assertEqual(cpu.r.iy, 0x1000)
        cpu.step()
        self.assertEqual(mem[0xFFF], 0x55)
        cpu.step()
        self.assertEqual(cpu.r.r, 6)

    def test_hex_constants_and_rst(self):
        result = Assembler().assemble("ld a,$C\nld b,0Ch\nrst 8")
        self.assertEqual(result.binary(False), bytes.fromhex("3e 0c 06 0c cf"))

    def test_halt_and_cycle_budget(self):
        cpu, _ = self.make("76")
        self.assertEqual(cpu.run(9), 12)
        self.assertTrue(cpu.halted)
        self.assertEqual(cpu.r.pc, 1)
        self.assertEqual(cpu.r.r, 3)


if __name__ == "__main__":
    unittest.main()
