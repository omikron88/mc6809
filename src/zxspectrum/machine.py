"""Spectrum 48K memory and ULA port, at instruction-level accuracy. GPL-3.0."""
from z80 import Z80


class Spectrum48:
    CPU_HZ = 3_500_000
    FRAME_CYCLES = 69_888
    IRQ_CYCLES = 32
    KEYS = (('CAPS SHIFT', 'Z', 'X', 'C', 'V'),
            ('A', 'S', 'D', 'F', 'G'),
            ('Q', 'W', 'E', 'R', 'T'),
            ('1', '2', '3', '4', '5'),
            ('0', '9', '8', '7', '6'),
            ('P', 'O', 'I', 'U', 'Y'),
            ('ENTER', 'L', 'K', 'J', 'H'),
            ('SPACE', 'SYMBOL SHIFT', 'M', 'N', 'B'))
    KEY_POSITIONS = {name: (row, bit) for row, names in enumerate(KEYS)
                     for bit, name in enumerate(names)}

    def __init__(self, rom):
        if len(rom) != 16_384:
            raise ValueError('ZX Spectrum 48K requires an exactly 16384-byte ROM')
        self.rom = bytes(rom)
        self.ram = bytearray(49_152)
        self.keys = set()
        self.ear = True
        self.border = 7
        self.mic = self.speaker = False
        self.beeper_events = []
        self.cpu = Z80(self.read, self.write, input_port=self.input,
                       output_port=self.output, intack=lambda: 255)

    def reset(self):
        """Reset CPU/ULA and release keys; retain RAM, as on a warm reset."""
        self.cpu.reset()
        self.keys.clear()
        self.border = 7
        self.mic = self.speaker = False
        self.beeper_events.clear()

    def read(self, address):
        address &= 65535
        return self.rom[address] if address < 0x4000 else self.ram[address - 0x4000]

    def write(self, address, value):
        address &= 65535
        if address >= 0x4000:
            self.ram[address - 0x4000] = value & 255

    def set_key(self, name, pressed=True):
        name = name.upper()
        if name not in self.KEY_POSITIONS:
            raise ValueError(f'Unknown Spectrum key: {name}')
        if pressed:
            self.keys.add(name)
        else:
            self.keys.discard(name)

    def input(self, port):
        # The ULA decodes only A0=0. High address lines select active-low rows.
        if port & 1:
            return 255
        value = 0xBF | (64 if self.ear else 0)
        for name in self.keys:
            row, bit = self.KEY_POSITIONS[name]
            if not port & (1 << (8 + row)):
                value &= ~(1 << bit)
        return value

    def output(self, port, value):
        if port & 1:
            return
        self.border = value & 7
        self.mic = bool(value & 8)
        speaker = bool(value & 16)
        if speaker != self.speaker:
            # Port callbacks run during an instruction; time is its start T-state.
            self.beeper_events.append((self.cpu.cycles, speaker))
            self.speaker = speaker

    def step(self):
        self.cpu.irq(self.cpu.cycles % self.FRAME_CYCLES < self.IRQ_CYCLES)
        return self.cpu.step()

    def run_frame(self):
        """Run to the next absolute frame boundary; keep instruction overshoot."""
        target = (self.cpu.cycles // self.FRAME_CYCLES + 1) * self.FRAME_CYCLES
        start = self.cpu.cycles
        while self.cpu.cycles < target:
            self.step()
        return self.cpu.cycles - start

    @property
    def flash_phase(self):
        return bool((self.cpu.cycles // self.FRAME_CYCLES // 16) & 1)
