"""Functional UART, unconnected PPI, CTC, and DS1302 models. GPL-3.0."""
from collections import deque
from datetime import datetime, timedelta


class UART16550:
    def __init__(self, transmit=lambda value: None):
        self.transmit = transmit
        self.rx = deque()
        self.reg = bytearray(8)
        self.divisor = bytearray([1, 0])
        self.fcr = 0
        self.thre_irq = True
        self.overrun = False

    def feed(self, data):
        # Host-side queue is intentionally unbounded: pasted text is not lost.
        self.rx.extend(data)

    def iir(self):
        if self.reg[1] & 4 and self.overrun:
            return 6
        if self.reg[1] & 1 and self.rx:
            return 4
        if self.reg[1] & 2 and self.thre_irq:
            return 2
        return 1

    @property
    def irq(self):
        return not self.iir() & 1

    def read(self, index):
        if index < 2 and self.reg[3] & 128:
            return self.divisor[index]
        if index == 0:
            return self.rx.popleft() if self.rx else 0
        if index == 2:
            value = self.iir()
            if value == 2:
                self.thre_irq = False
            return value | (0xC0 if self.fcr & 1 else 0)
        if index == 5:
            value = 0x60 | bool(self.rx) | (2 if self.overrun else 0)
            self.overrun = False
            return value
        if index == 6:
            # Loopback maps RTS,DTR,OUT1,OUT2 to CTS,DSR,RI,DCD.
            m = self.reg[4]
            return (((m & 2) << 3) | ((m & 1) << 5) |
                    ((m & 4) << 4) | ((m & 8) << 4)) if m & 16 else 0x10
        return self.reg[index]

    def write(self, index, value):
        if index < 2 and self.reg[3] & 128:
            self.divisor[index] = value
        elif index == 0:
            if self.reg[4] & 16:
                self.feed([value])
            else:
                self.transmit(value)
            self.thre_irq = True
        elif index == 2:
            self.fcr = value
            if value & 2:
                self.rx.clear()
            if value & 4:
                self.thre_irq = True
        elif index not in (5, 6):
            if index == 1 and value & 2 and not self.reg[1] & 2:
                self.thre_irq = True
            self.reg[index] = value


class PPI8255:
    """Mode 0 and bit set/reset; no peripheral attached, inputs pulled high."""
    def __init__(self):
        self.control = 0x9B
        self.latch = bytearray(3)

    def read(self, index):
        if index == 3:
            return 255  # control register is write only
        if index == 0:
            mask = 255 if self.control & 16 else 0
        elif index == 1:
            mask = 255 if self.control & 2 else 0
        else:
            mask = (240 if self.control & 8 else 0) | (15 if self.control & 1 else 0)
        return self.latch[index] | mask

    def write(self, index, value):
        if index != 3:
            self.latch[index] = value
        elif value & 128:
            self.control = value
            self.latch[:] = b'\0\0\0'
        else:
            bit = 1 << ((value >> 1) & 7)
            self.latch[2] = (self.latch[2] | bit) if value & 1 else (self.latch[2] & ~bit)


class CTC:
    """Instruction-granularity CTC; channel 0 external 921600 Hz, ZC0 -> CH1."""
    def __init__(self, cpu_hz):
        self.cpu_hz = cpu_hz
        self.vector = 0
        self.control = [3] * 4
        self.constant = [256] * 4
        self.count = [256] * 4
        self.waiting = [False] * 4
        self.running = [False] * 4
        self.phase = [0] * 4
        self.pending = [False] * 4
        self.service = []
        self.external_phase = 0
        self.level = [False] * 4

    def write(self, channel, value):
        if self.waiting[channel]:
            self.constant[channel] = self.count[channel] = value or 256
            self.phase[channel] = 0
            self.waiting[channel] = False
            self.running[channel] = bool(self.control[channel] & 64 or not self.control[channel] & 8)
            self.control[channel] &= ~2
        elif value & 1:
            self.control[channel] = value
            self.waiting[channel] = bool(value & 4)
            if value & 2:
                self.running[channel] = False
                self.pending[channel] = False
                self.phase[channel] = 0
            if not value & 128:
                self.pending[channel] = False
        elif channel == 0:
            self.vector = value & 0xF8

    def pulse(self, channel, pulses=1):
        if not self.running[channel] or not pulses:
            return 0
        left = self.count[channel] - pulses
        hits = 0
        if left <= 0:
            hits = (-left) // self.constant[channel] + 1
            left += hits * self.constant[channel]
            if self.control[channel] & 128:
                self.pending[channel] = True
        self.count[channel] = left
        return hits

    def trigger(self, channel, level):
        old = self.level[channel]
        self.level[channel] = level
        if old == level or level != bool(self.control[channel] & 16):
            return
        if self.control[channel] & 64:
            self.pulse(channel)
        elif not self.control[channel] & 2:
            self.running[channel] = True

    def tick(self, cycles):
        self.external_phase += cycles * 921600
        pulses, self.external_phase = divmod(self.external_phase, self.cpu_hz)
        output0 = self.pulse(0, pulses) if self.control[0] & 64 else 0
        if self.control[1] & 64:
            self.pulse(1, output0)
        elif output0 and not self.control[1] & 2:
            self.running[1] = True
        for ch in range(4):
            if not self.control[ch] & 64 and self.running[ch]:
                self.phase[ch] += cycles
                pulses, self.phase[ch] = divmod(self.phase[ch], 256 if self.control[ch] & 32 else 16)
                hits = self.pulse(ch, pulses)
                if ch == 0 and self.control[1] & 64:
                    self.pulse(1, hits)

    def source(self):
        ceiling = self.service[-1] if self.service else 4
        return next((ch for ch in range(ceiling) if self.pending[ch]), None)

    @property
    def irq(self):
        return self.source() is not None

    def acknowledge(self):
        ch = self.source()
        if ch is None:
            return 255
        self.pending[ch] = False
        self.service.append(ch)
        return self.vector | ch << 1

    def reti(self):
        if self.service:
            self.service.pop()


def bcd(value):
    return value // 10 * 16 + value % 10


def unbcd(value):
    return (value >> 4) * 10 + (value & 15)


class DS1302:
    """LSB-first three-wire RTC, clock and RAM bursts, write protection."""
    def __init__(self, now=None):
        self.base = (now or datetime.now()).replace(microsecond=0)
        self.elapsed = 0.0
        self.halted = False
        self.wp = 0
        self.trickle = 0
        self.hour12 = False
        self.ram = bytearray(31)
        self.pins = 0
        self._transaction()

    def _transaction(self):
        self.command = None
        self.bits = self.value = self.position = 0
        self.output = 0
        self.read_data = []

    def tick(self, seconds):
        if not self.halted:
            self.elapsed += seconds

    def clock(self):
        t = self.base + timedelta(seconds=int(self.elapsed))
        hour = bcd(t.hour)
        if self.hour12:
            hour = 128 | (32 if t.hour >= 12 else 0) | bcd(t.hour % 12 or 12)
        return [bcd(t.second) | (128 if self.halted else 0), bcd(t.minute), hour,
                bcd(t.day), bcd(t.month), t.isoweekday(), bcd(t.year % 100), self.wp, self.trickle]

    def _write_byte(self, value):
        ram = bool(self.command & 64)
        addr = (self.command >> 1) & 31
        burst = addr == 31
        index = self.position if burst else addr
        self.position += 1
        if ram:
            if index < 31 and not self.wp:
                self.ram[index] = value
            return
        if index == 7:
            self.wp = value & 128
            return
        if self.wp:
            return
        if index == 8:
            self.trickle = value
            return
        if index > 6:
            return
        values = self.clock()
        values[index] = value
        try:
            hour = values[2]
            h = (unbcd(hour & 31) % 12 + (12 if hour & 32 else 0)) if hour & 128 else unbcd(hour & 63)
            self.base = datetime(2000 + unbcd(values[6]), unbcd(values[4]), unbcd(values[3]),
                                 h, unbcd(values[1]), unbcd(values[0] & 127))
            self.elapsed = 0.0
            self.halted = bool(values[0] & 128)
            self.hour12 = bool(hour & 128)
        except ValueError:
            pass  # invalid intermediate clock values are ignored

    def write(self, value):
        old = self.pins
        self.pins = value
        if not value & 16:
            self._transaction()
            return
        if not old & 16:
            self._transaction()
        rising = not old & 64 and value & 64
        falling = old & 64 and not value & 64
        if rising and (self.command is None or not self.command & 1):
            # Board /WE bit 5 must be low to drive data toward the RTC.
            if value & 32:
                return
            self.value |= ((value >> 7) & 1) << self.bits
            self.bits += 1
            if self.bits == 8:
                if self.command is None:
                    self.command = self.value if self.value & 128 else 0
                    addr = (self.command >> 1) & 31
                    data = list(self.ram) if self.command & 64 else self.clock()
                    self.read_data = data if addr == 31 else data[addr:addr+1]
                else:
                    self._write_byte(self.value)
                self.bits = self.value = 0
        elif falling and self.command is not None and self.command & 1:
            byte = self.position // 8
            self.output = ((self.read_data[byte] >> (self.position % 8)) & 1) if byte < len(self.read_data) else 0
            self.position += 1
