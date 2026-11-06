"""Sample the ULA speaker latch; no cassette audio or analogue filter. GPL-3.0."""
from array import array
from collections import deque
import sys


class Beeper:
    def __init__(self, rate=44100):
        self.rate = rate
        self.sample = 0
        self.level = False
        self.events = deque()

    def render(self, machine):
        self.events.extend(machine.beeper_events)
        machine.beeper_events.clear()
        end = machine.cpu.cycles * self.rate // machine.CPU_HZ
        samples = array('h')
        while self.sample < end:
            cycle = self.sample * machine.CPU_HZ // self.rate
            while self.events and self.events[0][0] <= cycle:
                _, self.level = self.events.popleft()
            samples.append(6000 if self.level else 0)
            self.sample += 1
        if sys.byteorder != 'little':
            samples.byteswap()
        return samples.tobytes()
