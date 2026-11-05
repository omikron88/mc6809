import io
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from zeta2 import Zeta2
from zeta2.demo import demo_rom
from zeta2.devices import CTC
from zeta2.floppy import Disk


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.m = Zeta2(b''.join(bytes([p]) * 16384 for p in range(32)))

    def test_reset_mirrors_first_rom_page(self):
        for addr in (0, 0x4000, 0x8000, 0xFFFF):
            self.assertEqual(self.m.read(addr), 0)
        self.m.write(0, 123)
        self.assertEqual(self.m.read(0), 0)

    def test_four_banks_rom_ram_and_a20(self):
        for bank, page in enumerate([31, 32, 63, 64]):
            self.m.output(0xAB78 + bank, page)
        self.m.output(0x7F, 1)
        self.assertEqual(self.m.read(0), 31)
        self.m.write(0x4000, 12)
        self.m.write(0x8000, 34)
        self.assertEqual(self.m.ram[0], 12)
        self.assertEqual(self.m.ram[31 * 16384], 34)
        self.assertEqual(self.m.read(0xC000), 255)
        self.m.output(0x7C, 0)
        self.assertEqual(self.m.read(0x4000), 0)

    def test_reset_retains_battery_ram(self):
        self.m.ram[100] = 17
        self.m.output(0x7C, 1)
        self.m.reset()
        self.assertFalse(self.m.paging)
        self.assertEqual(self.m.ram[100], 17)
        self.assertIs(self.m.cpu.intack.__self__, self.m.ctc)


class SerialTests(unittest.TestCase):
    def test_uart_dlab_fifo_scratch_and_loopback(self):
        m = Zeta2(b'\x76')
        m.output(0x6B, 128)
        m.output(0x68, 12)
        m.output(0x69, 1)
        self.assertEqual(m.input(0x68), 12)
        self.assertEqual(m.input(0x69), 1)
        m.output(0x6B, 3)
        m.output(0x6F, 0xA5)
        self.assertEqual(m.input(0x6F), 0xA5)
        m.output(0x6A, 1)
        self.assertEqual(m.input(0x6A), 0xC1)
        m.output(0x6C, 0x1F)
        self.assertEqual(m.input(0x6E), 0xF0)
        m.output(0x68, 65)
        self.assertEqual(m.input(0x6D) & 1, 1)
        self.assertEqual(m.input(0x68), 65)
        self.assertEqual(m.input(0x6D) & 1, 0)

    def test_real_z80_boot_rom_and_echo(self):
        output = bytearray()
        m = Zeta2(demo_rom(), transmit=output.append)
        m.run(20000)
        self.assertIn(b'no ParPortProp', output)
        self.assertTrue(m.paging)
        m.uart.feed(b'Hello\r')
        m.run(10000)
        self.assertTrue(output.endswith(b'Hello\r'))

    def test_ppi_mode0_alias_and_bsr(self):
        m = Zeta2(b'\x76')
        self.assertEqual(m.input(0x64), 255)
        m.output(0x67, 0x80)
        m.output(0x60, 0x12)
        self.assertEqual(m.input(0x64), 0x12)
        m.output(0x63, 7)
        self.assertEqual(m.input(0x62), 8)
        m.output(0x63, 6)
        self.assertEqual(m.input(0x62), 0)


class InterruptTests(unittest.TestCase):
    def test_counter_chain_15hz(self):
        c = CTC(8_000_000)
        for ch, value in [(0, 0x47), (0, 0), (1, 0xC7), (1, 240), (0, 0xD0)]:
            c.write(ch, value)
        c.tick(533333)
        self.assertFalse(c.irq)
        c.tick(1)
        self.assertTrue(c.irq)
        self.assertEqual(c.acknowledge(), 0xD2)
        self.assertFalse(c.irq)
        c.reti()

    def test_priority_and_reti(self):
        c = CTC(8_000_000)
        c.pending[:] = [False, False, True, True]
        self.assertEqual(c.acknowledge(), 4)
        self.assertFalse(c.irq)
        c.pending[1] = True
        self.assertEqual(c.acknowledge(), 2)
        c.reti()
        self.assertFalse(c.irq)
        c.reti()
        self.assertEqual(c.acknowledge(), 6)

    def test_z80_im2_and_reti_fetch(self):
        m = Zeta2(b'\x76')
        m.pages[:] = [32, 33, 34, 35]
        m.paging = True
        # IM2 table 8000 + vector 42 points to 0100.
        m.write(0x8042, 0)
        m.write(0x8043, 1)
        # ISR: LD A,55; LD (4000),A; EI; RETI
        for i, b in enumerate(bytes.fromhex('3e55320040fbed4d')):
            m.write(0x100 + i, b)
        m.cpu.r.pc = 0x200
        m.cpu.r.sp = 0xFFFE
        m.cpu.r.i = 128
        m.cpu.im = 2
        m.cpu.iff1 = True
        m.ctc.vector = 0x40
        m.ctc.pending[1] = True
        m.step()
        self.assertEqual(m.cpu.r.pc, 0x100)
        for _ in range(4):
            m.step()
        self.assertEqual(m.read(0x4000), 0x55)
        self.assertEqual(m.cpu.r.pc, 0x200)
        self.assertEqual(m.ctc.service, [])

    def test_timer_prescaler(self):
        c = CTC(8_000_000)
        c.write(3, 0x87)
        c.write(3, 2)
        c.tick(31)
        self.assertFalse(c.irq)
        c.tick(1)
        self.assertTrue(c.irq)


class RTCTests(unittest.TestCase):
    def setUp(self):
        self.m = Zeta2(b'\x76', rtc_now=datetime(2026, 11, 5, 12, 34, 56))

    def send(self, value):
        for bit in range(8):
            pins = 16 | (((value >> bit) & 1) << 7)
            self.m.output(0x70, pins)
            self.m.output(0x70, pins | 64)
            self.m.output(0x70, pins)

    def read(self, command, count=1):
        self.m.output(0x70, 0)
        self.send(command)
        data = []
        # Falling edge of last command clock has already presented bit 0.
        for _ in range(count):
            value = 0
            for bit in range(8):
                value |= (self.m.input(0x70) & 1) << bit
                self.m.output(0x70, 16 | 32 | 64)
                self.m.output(0x70, 16 | 32)
            data.append(value)
        self.m.output(0x70, 0)
        return data

    def write(self, command, values):
        self.m.output(0x70, 0)
        self.send(command)
        for value in values:
            self.send(value)
        self.m.output(0x70, 0)

    def test_clock_bcd_burst_and_jumper(self):
        self.assertEqual(self.read(0xBF, 8), [0x56, 0x34, 0x12, 5, 0x11, 4, 0x26, 0])
        self.assertEqual(self.m.input(0x70) & 64, 0)

    def test_ram_burst_and_write_protect(self):
        self.write(0xFE, list(range(31)))
        self.assertEqual(self.read(0xFF, 31), list(range(31)))
        self.write(0x8E, [128])
        self.write(0xC0, [99])
        self.assertEqual(self.read(0xC1), [0])
        self.write(0x8E, [0])
        self.write(0xC0, [99])
        self.assertEqual(self.read(0xC1), [99])

    def test_halt_and_emulated_time(self):
        self.m.rtc.tick(5)
        self.assertEqual(self.read(0x81), [1])
        self.write(0x80, [0x89])
        self.m.rtc.tick(100)
        self.assertEqual(self.read(0x81), [0x89])


class FloppyTests(unittest.TestCase):
    def setUp(self):
        self.disk = Disk(bytes(range(256)) * (737280 // 256), writable=True)
        self.m = Zeta2(b'\x76', drives=[self.disk, None])
        self.m.output(0x38, 0)
        self.m.output(0x3F, 0x0C)

    def command(self, *data):
        for value in data:
            self.m.output(0x33, value)

    def result(self):
        return [self.m.input(0x37) for _ in range(7)]

    def test_reset_sense_and_seek(self):
        self.command(8)
        self.assertEqual([self.m.input(0x31) for _ in range(2)], [0xC0, 0])
        for _ in range(3):
            self.command(8)
            self.m.input(0x31)
            self.m.input(0x31)
        self.command(15, 0, 12)
        self.command(8)
        self.assertEqual([self.m.input(0x31) for _ in range(2)], [0x20, 12])

    def test_read_sector_and_port_aliases(self):
        self.command(0x46, 0, 0, 0, 1, 2, 1, 0x1B, 0xFF)
        self.assertEqual(self.m.input(0x34), 0xF0)
        self.assertEqual(bytes(self.m.input(0x31) for _ in range(512)), bytes(range(256)) * 2)
        self.assertEqual(self.result(), [0, 0, 0, 0, 0, 1, 2])
        self.assertEqual(self.m.input(0x30), 0x80)

    def test_write_sector_and_save(self):
        self.command(0x45, 0, 0, 0, 2, 2, 2, 0x1B, 0xFF)
        for _ in range(512):
            self.m.output(0x31, 0xAA)
        self.assertEqual(self.result()[0:3], [0, 0, 0])
        self.assertEqual(self.disk.data[512:1024], b'\xAA' * 512)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'disk.img'
            self.disk.save(path)
            self.assertEqual(path.read_bytes()[512:1024], b'\xAA' * 512)

    def test_terminal_count_after_one_sector(self):
        self.command(0x46, 0, 0, 0, 1, 2, 9, 0x1B, 0xFF)
        for _ in range(512):
            self.m.input(0x31)
        self.m.input(0x3E)
        self.assertEqual(self.result(), [0, 0, 0, 0, 0, 1, 2])

    def test_format_track(self):
        self.command(0x4D, 0, 2, 2, 0x1B, 0xE5)
        for value in [0, 0, 1, 2, 0, 0, 2, 2]:
            self.m.output(0x31, value)
        self.assertEqual(self.result()[:3], [0, 0, 0])
        self.assertEqual(self.disk.data[:1024], b'\xE5' * 1024)

    def test_missing_disk_and_write_protect(self):
        self.command(0x46, 1, 0, 0, 1, 2, 1, 0x1B, 0xFF)
        result = self.result()
        self.assertTrue(result[0] & 0x48)
        self.disk.writable = False
        self.command(0x45, 0, 0, 0, 1, 2, 1, 0x1B, 0xFF)
        self.assertEqual(self.result()[1], 2)


class CLITests(unittest.TestCase):
    def test_headless_demo_and_state_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            ram, rtc = Path(tmp) / 'ram.bin', Path(tmp) / 'rtc.json'
            result = subprocess.run([sys.executable, '-m', 'zeta2', '--demo', '--headless',
                                     '--cycles', '20000', '--ram', str(ram), '--rtc-state', str(rtc)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(b'Zeta2 Python', result.stdout)
            self.assertEqual(ram.stat().st_size, 524288)
            self.assertIn('"ram"', rtc.read_text())

    def test_bad_rom_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'empty.rom'
            path.write_bytes(b'')
            result = subprocess.run([sys.executable, '-m', 'zeta2', '--rom', str(path), '--headless', '--cycles', '1'],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertIn(b'ROM must', result.stderr)


if __name__ == '__main__':
    unittest.main()
