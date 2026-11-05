"""Zeta SBC V2 memory map and I/O bus. GPL-3.0."""
from z80 import Z80
from .devices import UART16550, PPI8255, CTC, DS1302
from .floppy import FDC37C65


class Zeta2:
    def __init__(self, rom, *, cpu_hz=8_000_000, transmit=lambda value: None,
                 drives=None, rtc_now=None, config_jumper=True, trace=None):
        if not 0 < len(rom) <= 512 * 1024:
            raise ValueError('ROM must contain 1 to 524288 bytes')
        if cpu_hz <= 0:
            raise ValueError('CPU frequency must be positive')
        self.rom = bytes(rom).ljust(512 * 1024, b'\xFF')
        self.ram = bytearray(512 * 1024)
        self.cpu_hz = cpu_hz
        self.pages = [0] * 4
        self.paging = False
        self.uart = UART16550(transmit)
        self.ppi = PPI8255()
        self.ctc = CTC(cpu_hz)
        self.rtc = DS1302(rtc_now)
        self.fdc = FDC37C65(drives)
        self.config_jumper = config_jumper
        self.trace = trace
        self._last_fetch = None
        self.cpu = Z80(self.read, self.write, fetch=self.fetch, intack=self.ctc.acknowledge,
                       input_port=self.input, output_port=self.output)

    def reset(self):
        """Hard reset; battery-backed RAM and RTC retain contents."""
        self.paging = False
        self.pages[:] = [0] * 4  # deterministic choice for undefined power-on latches
        self.cpu.reset()
        self.ctc = CTC(self.cpu_hz)
        self.cpu.intack = self.ctc.acknowledge
        self.uart = UART16550(self.uart.transmit)
        self.ppi = PPI8255()
        self.fdc.dor = 0
        self.fdc.reset()
        self._last_fetch = None

    def physical(self, address):
        address &= 65535
        page = self.pages[address >> 14] if self.paging else 0
        # A20 is decoded: page selects 64..127 have no on-board memory.
        return page * 16384 + (address & 16383)

    def read(self, address):
        physical = self.physical(address)
        if physical < 0x80000:
            return self.rom[physical]
        if physical < 0x100000:
            return self.ram[physical - 0x80000]
        return 255

    def fetch(self, address):
        value = self.read(address)
        # Z80 daisy-chain devices recognize RETI on M1 fetches (ED 4D).
        if self._last_fetch == 0xED and value == 0x4D:
            self.ctc.reti()
        self._last_fetch = value
        return value

    def write(self, address, value):
        physical = self.physical(address)
        if 0x80000 <= physical < 0x100000:
            self.ram[physical - 0x80000] = value & 255

    def input(self, port):
        p = port & 255
        value = 255
        if 0x20 <= p <= 0x27:
            value = self.ctc.count[p & 3] & 255
        elif 0x30 <= p <= 0x37:
            value = self.fdc.read() if p & 1 else self.fdc.status()
        elif 0x38 <= p <= 0x3F:
            value = self.fdc.terminal_count()
        elif 0x60 <= p <= 0x67:
            value = self.ppi.read(p & 3)
        elif 0x68 <= p <= 0x6F:
            value = self.uart.read(p & 7)
        elif 0x70 <= p <= 0x77:
            # JP1 installed grounds CONFIG, selecting the serial console.
            value = self.rtc.output | (0 if self.config_jumper else 64)
        if self.trace:
            self.trace('in', port & 65535, value)
        return value

    def output(self, port, value):
        p, value = port & 255, value & 255
        if self.trace:
            self.trace('out', port & 65535, value)
        if 0x20 <= p <= 0x27:
            self.ctc.write(p & 3, value)
        elif 0x28 <= p <= 0x2F:
            self.fdc.ccr = value
        elif 0x30 <= p <= 0x37 and p & 1:
            self.fdc.write(value)
        elif 0x38 <= p <= 0x3F:
            self.fdc.set_dor(value)
        elif 0x60 <= p <= 0x67:
            self.ppi.write(p & 3, value)
        elif 0x68 <= p <= 0x6F:
            self.uart.write(p & 7, value)
        elif 0x70 <= p <= 0x77:
            self.rtc.write(value)
        elif 0x78 <= p <= 0x7B:
            self.pages[p & 3] = value & 127
        elif 0x7C <= p <= 0x7F:
            self.paging = bool(value & 1)

    def step(self):
        self.ctc.trigger(2, self.uart.irq)
        self.cpu.irq(self.ctc.irq)
        cycles = self.cpu.step()
        self.ctc.tick(cycles)
        self.rtc.tick(cycles / self.cpu_hz)
        return cycles

    def run(self, cycles, *, stop_on_halt=False):
        if cycles < 0:
            raise ValueError('Negative cycle budget')
        start = self.cpu.cycles
        while self.cpu.cycles - start < cycles:
            self.step()
            if stop_on_halt and self.cpu.halted:
                break
        return self.cpu.cycles - start
