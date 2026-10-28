import unittest
from z80 import Z80, Assembler, AssemblyError, INSTRUCTIONS, BY_OPCODE, disassemble_one
from z80.instructions import validate
from z80.cpu import S, Z, H, PV, N, C


class Z80Tests(unittest.TestCase):
    def cpu(self, code, origin=0):
        mem = bytearray(65536)
        mem[origin : origin + len(code)] = code
        cpu = Z80(mem.__getitem__, mem.__setitem__)
        cpu.r.pc = origin
        return cpu, mem

    def test_catalogue(self):
        validate()
        self.assertEqual(sum(i.is_i8080 for i in INSTRUCTIONS), 244)
        self.assertTrue(BY_OPCODE[b"\xeb"].is_i8080)
        for key in (b"\x18", b"\xcb\x00", b"\xed\x44", b"\xdd\x21"):
            self.assertFalse(BY_OPCODE[key].is_i8080)
        self.assertEqual(len([i for i in INSTRUCTIONS if i.opcode[:1] == b"\xcb"]), 256)

    def test_decode_every_encoding(self):
        for i in INSTRUCTIONS:
            with self.subTest(code=i.opcode.hex()):
                code = (
                    i.opcode[:2] + b"\x02" + i.opcode[2:]
                    if i.displacement_before_opcode
                    else i.opcode
                )
                code += bytes(i.byte_count - len(code))
                d = disassemble_one(lambda a: code[a], 0)
                self.assertEqual(d.instruction, i)
                self.assertEqual(d.next_address, i.byte_count)
                result = (
                    Assembler(allow_undocumented=True).assemble(d.text).binary(False)
                )
                d2 = disassemble_one(result.__getitem__, 0)
                self.assertEqual(d2.text, d.text)

    def test_execute_every_encoding(self):
        for i in INSTRUCTIONS:
            with self.subTest(code=i.opcode.hex()):
                code = (
                    i.opcode[:2] + b"\x02" + i.opcode[2:]
                    if i.displacement_before_opcode
                    else i.opcode
                )
                cpu, mem = self.cpu(code + bytes(4))
                cpu.r.sp = 0x9000
                cpu.r.hl = 0x8000
                cpu.r.ix = 0x8100
                cpu.r.iy = 0x8200
                t = cpu.step()
                self.assertIn(t, (i.cycles, i.cycles_taken))

    def test_assembled_program(self):
        result = Assembler().assemble("""org $100
ld sp,$f000
ld ix,$8000
ld (ix-2),$7f
inc (ix-2)
ld a,(ix-2)
add a,$80
call subr
halt
subr: ld ($9000),a
ret
""")
        cpu = Z80(result.memory.__getitem__, result.memory.__setitem__)
        cpu.r.pc = 0x100
        for _ in range(10):
            cpu.step()
        self.assertTrue(cpu.halted)
        self.assertEqual(result.memory[0x7FFE], 128)
        self.assertEqual(result.memory[0x9000], 0)
        self.assertEqual(cpu.r.sp, 0xF000)
        self.assertEqual(cpu.r.f & (Z | PV | C), Z | PV | C)

    def test_8080_filter(self):
        self.assertEqual(
            Assembler(i8080_only=True).assemble("LD A,42\nADD A,B").binary(False),
            bytes([0x3E, 42, 0x80]),
        )
        for text in ("JR 0", "LD IX,1", "BIT 0,A", "NEG", "EXX"):
            with self.assertRaises(AssemblyError):
                Assembler(i8080_only=True).assemble(text)

    def test_arithmetic_exhaustive(self):
        cpu, mem = self.cpu(b"\x80")
        for a in range(256):
            for b in range(256):
                cpu.r.a = a
                cpu._alu(0, b)
                out = (a + b) & 255
                self.assertEqual(cpu.r.a, out)
                self.assertEqual(bool(cpu.r.f & C), a + b > 255)
                self.assertEqual(bool(cpu.r.f & H), (a & 15) + (b & 15) > 15)
                self.assertEqual(bool(cpu.r.f & PV), bool(~(a ^ b) & (a ^ out) & 128))
                cpu.r.a = a
                cpu._alu(2, b)
                out = (a - b) & 255
                self.assertEqual(cpu.r.a, out)
                self.assertEqual(bool(cpu.r.f & C), a < b)
                self.assertEqual(bool(cpu.r.f & H), (a & 15) < (b & 15))
                self.assertEqual(bool(cpu.r.f & PV), bool((a ^ b) & (a ^ out) & 128))

    def test_block_transfer(self):
        cpu, mem = self.cpu(b"\xed\xb0")
        cpu.r.hl = 0x1000
        cpu.r.de = 0x2000
        cpu.r.bc = 3
        mem[0x1000:0x1003] = b"abc"
        self.assertEqual([cpu.step() for _ in range(3)], [21, 21, 16])
        self.assertEqual(mem[0x2000:0x2003], b"abc")
        self.assertEqual(cpu.r.pc, 2)

    def test_ports(self):
        cpu, mem = self.cpu(bytes.fromhex("3e12d334db56"))
        events = []
        cpu.output_port = lambda p, v: events.append((p, v))
        cpu.input_port = lambda p: 0x78
        for _ in range(3):
            cpu.step()
        self.assertEqual(events, [(0x1234, 0x12)])
        self.assertEqual(cpu.r.a, 0x78)

    def test_interrupt_delay_and_return(self):
        cpu, mem = self.cpu(bytes.fromhex("fb0076"))
        cpu.im = 1
        cpu.irq()
        mem[0x38:0x3A] = bytes.fromhex("ed4d")
        self.assertEqual(cpu.step(), 4)
        self.assertEqual(cpu.step(), 4)
        self.assertEqual(cpu.step(), 13)
        self.assertEqual(cpu.r.pc, 0x38)
        self.assertEqual(cpu.step(), 14)
        self.assertEqual(cpu.r.pc, 2)
        cpu.nmi()
        self.assertEqual(cpu.step(), 11)
        self.assertEqual(cpu.r.pc, 0x66)

    def test_prefix_aliases_and_wrap(self):
        cpu, mem = self.cpu(bytes.fromhex("ddfd213412"))
        self.assertEqual(cpu.step(), 18)
        self.assertEqual(cpu.r.iy, 0x1234)
        self.assertEqual(cpu.r.r, 3)
        mem[65535] = 0x3E
        mem[0] = 42
        cpu.r.pc = 65535
        self.assertEqual(cpu.step(), 7)
        self.assertEqual(cpu.r.a, 42)
        self.assertEqual(cpu.r.pc, 1)

    def test_index_cb(self):
        cpu, mem = self.cpu(bytes.fromhex("ddcbff00"))
        cpu.r.ix = 0x8000
        mem[0x7FFF] = 0x81
        self.assertEqual(cpu.step(), 23)
        self.assertEqual(mem[0x7FFF], 3)
        self.assertEqual(cpu.r.b, 3)
        self.assertTrue(cpu.r.f & C)

    def test_errors(self):
        for source in (
            "JR $1000",
            "LD A,256",
            "LD (IX+128),A",
            "DB 256",
            "ORG 65536",
            "X: NOP\nX: NOP",
            "LD A,UNKNOWN",
        ):
            with self.subTest(source=source), self.assertRaises(AssemblyError):
                Assembler().assemble(source)


if __name__ == "__main__":
    unittest.main()
