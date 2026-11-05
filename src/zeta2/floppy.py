"""WD37C65/765 functional non-DMA floppy controller. GPL-3.0."""
from collections import deque
from pathlib import Path


class Disk:
    GEOMETRIES = {163840: (40, 1, 8), 184320: (40, 1, 9), 327680: (40, 2, 8),
                  368640: (40, 2, 9), 737280: (80, 2, 9), 1228800: (80, 2, 15),
                  1474560: (80, 2, 18)}

    def __init__(self, data, *, writable=False, geometry=None):
        self.data = bytearray(data)
        self.geometry = geometry or self.GEOMETRIES.get(len(data))
        if self.geometry is None or len(data) != self.geometry[0] * self.geometry[1] * self.geometry[2] * 512:
            raise ValueError('Unsupported raw disk image size/geometry')
        self.writable = writable
        self.dirty = False

    def offset(self, c, h, r, n):
        tracks, heads, sectors = self.geometry
        if not (0 <= c < tracks and 0 <= h < heads and 1 <= r <= sectors and n == 2):
            raise ValueError('Sector not found')
        return ((c * heads + h) * sectors + r - 1) * 512

    def save(self, path):
        if self.dirty and self.writable:
            target = Path(path)
            temporary = target.with_name(target.name + '.tmp')
            temporary.write_bytes(self.data)
            temporary.replace(target)
            self.dirty = False


class FDC37C65:
    LENGTHS = {2: 9, 3: 3, 4: 2, 5: 9, 6: 9, 7: 2, 8: 1,
               9: 9, 10: 2, 12: 9, 13: 6, 15: 3, 16: 1}

    def __init__(self, drives=None):
        self.drives = list(drives or [None, None])
        self.cylinder = [0] * 4
        self.dor = 0
        self.ccr = 0
        self.reset()

    def reset(self):
        self.command = []
        self.result = deque()
        self.events = deque()
        self.buffer = bytearray()
        self.pos = 0
        self.phase = 'command'
        self.transfer = []
        self.last = [0, 0, 1, 2]
        self.st0 = 0
        self.non_dma = True

    def set_dor(self, value):
        old = self.dor
        self.dor = value
        # Integrated DOR: bit 2 releases software reset (RomWBW DOR_INIT=0Ch).
        if not value & 4:
            self.reset()
        elif not old & 4:
            self.events.extend((0xC0 | d, self.cylinder[d]) for d in range(4))

    def status(self):
        if self.phase == 'read':
            return 0xF0
        if self.phase in ('write', 'format'):
            return 0xB0
        if self.result:
            return 0xD0
        return 0x90 if self.command else 0x80

    def _result(self, values):
        self.result = deque(values)
        self.phase = 'result'
        self.command = []

    def _finish(self, st1=0, st2=0):
        self._result([self.st0 | (0x40 if st1 or st2 else 0), st1, st2] + self.last)

    def terminal_count(self):
        if self.phase in ('read', 'write', 'format'):
            self._finish()
        return 255

    def read(self):
        if self.phase == 'read':
            value = self.buffer[self.pos]
            self.pos += 1
            self.last = list(self.transfer[(self.pos - 1) // 512][1])
            if self.pos >= len(self.buffer):
                self._finish()
            return value
        if self.result:
            value = self.result.popleft()
            if not self.result:
                self.phase = 'command'
            return value
        return 255

    def write(self, value):
        if self.phase in ('write', 'format'):
            self.buffer.append(value)
            if self.phase == 'write' and len(self.buffer) % 512 == 0:
                disk = self.drives[self.drive]
                offset, chrn = self.transfer[len(self.buffer) // 512 - 1]
                disk.data[offset:offset+512] = self.buffer[-512:]
                disk.dirty = True
                self.last = list(chrn)
            target = len(self.transfer) * 512 if self.phase == 'write' else self.command[3] * 4
            if len(self.buffer) >= target:
                if self.phase == 'format':
                    disk = self.drives[self.drive]
                    try:
                        for i in range(0, len(self.buffer), 4):
                            chrn = list(self.buffer[i:i+4])
                            offset = disk.offset(*chrn)
                            disk.data[offset:offset+512] = bytes([self.command[5]]) * 512
                            disk.dirty = True
                            self.last = chrn
                    except ValueError:
                        self._finish(4)
                        return
                self._finish()
            return
        if self.result:
            return
        self.command.append(value)
        op = self.command[0] & 31
        if len(self.command) < self.LENGTHS.get(op, 1):
            return
        self._execute(op)

    def _execute(self, op):
        cmd = self.command
        if op == 3:
            self.non_dma = bool(cmd[2] & 1)
            self.command = []
            return
        if op == 8:
            self._result(list(self.events.popleft()) if self.events else [0x80])
            return
        if op == 16:
            self._result([0x80])  # original 765 / 37C65, no enhanced VERSION
            return
        if op not in (2, 4, 5, 6, 7, 9, 10, 12, 13, 15):
            self._result([0x80])
            return
        self.drive = cmd[1] & 3
        head = (cmd[1] >> 2) & 1
        self.st0 = cmd[1] & 7
        disk = self.drives[self.drive] if self.drive < len(self.drives) else None
        if op == 4:
            st3 = self.st0 | (16 if self.cylinder[self.drive] == 0 else 0)
            if disk:
                st3 |= 32 | (8 if disk.geometry[1] == 2 else 0) | (0 if disk.writable else 64)
            self._result([st3])
            return
        if op in (7, 15):
            self.cylinder[self.drive] = 0 if op == 7 else cmd[2]
            self.events.append((self.st0 | (0x20 if disk else 0x68), self.cylinder[self.drive]))
            self.command = []
            return
        self.last = [self.cylinder[self.drive], head, 1, 2]
        if not disk:
            self.st0 |= 0x48
            self._finish(4)
            return
        if op == 10:
            self._finish()
            return
        if op in (9, 12):
            # Raw images cannot represent deleted data marks.
            self._finish(4)
            return
        if op in (5, 13) and not disk.writable:
            self._finish(2)
            return
        self.buffer = bytearray()
        self.pos = 0
        if op == 13:
            self.transfer = []
            if cmd[2] != 2 or cmd[3] == 0:
                self._finish(4)
            else:
                self.phase = 'format'
            return
        c, h, r, n, eot = cmd[2:7]
        self.last = [c, h, r, n]
        self.transfer = []
        try:
            if c != self.cylinder[self.drive] or h != head or r > eot:
                raise ValueError('Wrong cylinder/head/sector')
            heads = [h, 1] if cmd[0] & 128 and h == 0 else [h]
            for current_head in heads:
                for sector in range(r if current_head == h else 1, eot + 1):
                    chrn = (c, current_head, sector, n)
                    offset = disk.offset(*chrn)
                    self.transfer.append((offset, chrn))
                    if op in (2, 6):
                        self.buffer.extend(disk.data[offset:offset+512])
        except ValueError:
            self._finish(4)
            return
        self.phase = 'read' if op in (2, 6) else 'write'
