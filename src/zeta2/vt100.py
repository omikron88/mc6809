"""VT100 screen and byte-stream parser, independent of the GUI. GPL-3.0."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    char: str = ' '
    bold: bool = False
    underline: bool = False
    blink: bool = False
    reverse: bool = False


GRAPHICS = dict(zip('`abcdefghijklmnopqrstuvwxyz{|}~',
                    '◆▒␉␌␍␊°±␤␋┘┐┌└┼⎺⎻─⎼⎽├┤┴┬│≤≥π≠£·'))


class VT100:
    def __init__(self, send=lambda data: None, bell=lambda: None, columns=80, rows=24):
        self.send, self.bell = send, bell
        self.default_columns, self.rows = columns, rows
        self.reset()

    def reset(self):
        self.columns = self.default_columns
        self.screen = [[Cell() for _ in range(self.columns)] for _ in range(self.rows)]
        self.x = self.y = 0
        self.top, self.bottom = 0, self.rows - 1
        self.bold = self.underline = self.blink = self.reverse = False
        self.origin = False
        self.autowrap = True
        self.wrap_pending = False
        self.cursor_keys = self.keypad = self.newline = self.insert = False
        self.reverse_screen = False
        self.cursor_visible = True
        self.g0 = self.g1 = 'B'
        self.charset = 0
        self.tabs = set(range(8, self.columns, 8))
        self.saved = None
        self.state = 'normal'
        self.sequence = ''
        self.dirty = True

    @property
    def lines(self):
        return [''.join(cell.char for cell in line) for line in self.screen]

    def feed(self, data):
        if isinstance(data, int):
            self.byte(data)
        else:
            for value in data:
                self.byte(value)

    def blank(self):
        return [Cell() for _ in range(self.columns)]

    def home(self):
        self.x = 0
        self.y = self.top if self.origin else 0
        self.wrap_pending = False

    def index(self):
        if self.y == self.bottom:
            del self.screen[self.top]
            self.screen.insert(self.bottom, self.blank())
        else:
            self.y = min(self.rows - 1, self.y + 1)
        self.dirty = True

    def reverse_index(self):
        if self.y == self.top:
            del self.screen[self.bottom]
            self.screen.insert(self.top, self.blank())
        else:
            self.y = max(0, self.y - 1)
        self.dirty = True

    def save(self):
        self.saved = (self.x, self.y, self.bold, self.underline, self.blink,
                      self.reverse, self.origin, self.autowrap, self.g0, self.g1, self.charset)

    def restore(self):
        if self.saved:
            (self.x, self.y, self.bold, self.underline, self.blink,
             self.reverse, self.origin, self.autowrap, self.g0, self.g1, self.charset) = self.saved
            self.x = min(self.x, self.columns - 1)
            self.y = min(self.y, self.rows - 1)
        else:
            self.home()
        self.wrap_pending = False

    def byte(self, value):
        value &= 127  # VT100 is a seven-bit terminal; ignore serial parity.
        if value == 27:
            self.state, self.sequence = 'escape', ''
            return
        if value in (24, 26):  # CAN/SUB cancel an escape sequence
            self.state = 'normal'
            return
        if value < 32 or value == 127:
            self.control(value)
            return
        if self.state == 'csi':
            if 0x40 <= value <= 0x7E:
                self.csi(chr(value), self.sequence)
                self.state, self.sequence = 'normal', ''
            elif len(self.sequence) < 128:
                self.sequence += chr(value)
            else:
                self.state = 'normal'
            self.dirty = True
            return
        if self.state in ('g0', 'g1'):
            setattr(self, self.state, chr(value))
            self.state = 'normal'
            return
        if self.state == 'hash':
            if value == ord('8'):
                self.screen = [[Cell('E') for _ in range(self.columns)] for _ in range(self.rows)]
                self.dirty = True
            self.state = 'normal'
            return
        if self.state == 'escape':
            self.state = 'normal'
            char = chr(value)
            if char == '[':
                self.state = 'csi'
            elif char in '()':
                self.state = 'g0' if char == '(' else 'g1'
            elif char == '#':
                self.state = 'hash'
            elif char == '7':
                self.save()
            elif char == '8':
                self.restore()
            elif char == 'D':
                self.wrap_pending = False
                self.index()
            elif char == 'M':
                self.wrap_pending = False
                self.reverse_index()
            elif char == 'E':
                self.x, self.wrap_pending = 0, False
                self.index()
            elif char == 'H':
                self.tabs.add(self.x)
            elif char == '=':
                self.keypad = True
            elif char == '>':
                self.keypad = False
            elif char == 'Z':
                self.send(b'\x1b[?1;2c')
            elif char == 'c':
                self.reset()
            self.dirty = True
            return
        self.print_char(chr(value))

    def control(self, value):
        if value == 7:
            self.bell()
        elif value == 8:
            self.x = max(0, self.x - 1)
            self.wrap_pending = False
        elif value == 9:
            self.x = next((x for x in sorted(self.tabs) if x > self.x), self.columns - 1)
            self.wrap_pending = False
        elif value in (10, 11, 12):
            self.wrap_pending = False
            self.index()
            if self.newline:
                self.x = 0
        elif value == 13:
            self.x, self.wrap_pending = 0, False
        elif value in (14, 15):
            self.charset = 1 if value == 14 else 0
        self.dirty = True

    def print_char(self, char):
        if self.wrap_pending:
            if self.autowrap:
                self.x = 0
                self.index()
            self.wrap_pending = False
        charset = self.g1 if self.charset else self.g0
        if charset == '0':
            char = GRAPHICS.get(char, char)
        elif charset == 'A' and char == '#':
            char = '£'
        line = self.screen[self.y]
        if self.insert:
            line.insert(self.x, Cell())
            line.pop()
        line[self.x] = Cell(char, self.bold, self.underline, self.blink, self.reverse)
        if self.x == self.columns - 1:
            self.wrap_pending = self.autowrap
        else:
            self.x += 1
        self.dirty = True

    def csi(self, final, sequence):
        private = sequence.startswith('?')
        if private:
            sequence = sequence[1:]
        if any(c not in '0123456789;' for c in sequence):
            return
        try:
            params = [int(p) if p else 0 for p in sequence.split(';')]
        except ValueError:
            return
        n = params[0] or 1
        lo, hi = (self.top, self.bottom) if self.origin else (0, self.rows - 1)
        if final in 'ABCDHfJKr':
            self.wrap_pending = False
        if final in 'hl':
            enabled = final == 'h'
            for p in params:
                if private:
                    if p == 1:
                        self.cursor_keys = enabled
                    elif p == 3:
                        self.columns = 132 if enabled else 80
                        self.screen = [self.blank() for _ in range(self.rows)]
                        self.top, self.bottom = 0, self.rows - 1
                        self.tabs = set(range(8, self.columns, 8))
                        self.home()
                    elif p == 5:
                        self.reverse_screen = enabled
                    elif p == 6:
                        self.origin = enabled
                        self.home()
                    elif p == 7:
                        self.autowrap = enabled
                    elif p == 25:
                        self.cursor_visible = enabled  # common later DEC extension
                elif p == 20:
                    self.newline = enabled
                elif p == 4:
                    self.insert = enabled
            return
        if private:
            return
        if final == 'A':
            self.y = max(lo, self.y - n)
        elif final == 'B':
            self.y = min(hi, self.y + n)
        elif final == 'C':
            self.x = min(self.columns - 1, self.x + n)
        elif final == 'D':
            self.x = max(0, self.x - n)
        elif final in 'Hf':
            self.y = min(hi, lo + n - 1)
            self.x = min(self.columns - 1, (params[1] or 1) - 1) if len(params) > 1 else 0
        elif final == 'J':
            mode = params[0]
            if mode == 0:
                self.screen[self.y][self.x:] = [Cell()] * (self.columns - self.x)
                for y in range(self.y + 1, self.rows):
                    self.screen[y] = self.blank()
            elif mode == 1:
                for y in range(self.y):
                    self.screen[y] = self.blank()
                self.screen[self.y][:self.x+1] = [Cell()] * (self.x + 1)
            elif mode == 2:
                self.screen = [self.blank() for _ in range(self.rows)]
        elif final == 'K':
            mode = params[0]
            if mode in (0, 1, 2):
                start = self.x if mode == 0 else 0
                end = self.x + 1 if mode == 1 else self.columns
                self.screen[self.y][start:end] = [Cell()] * (end - start)
        elif final == 'm':
            for p in params:
                if p == 0:
                    self.bold = self.underline = self.blink = self.reverse = False
                elif p in (1, 4, 5, 7):
                    setattr(self, {1: 'bold', 4: 'underline', 5: 'blink', 7: 'reverse'}[p], True)
                elif p in (22, 24, 25, 27):
                    setattr(self, {22: 'bold', 24: 'underline', 25: 'blink', 27: 'reverse'}[p], False)
        elif final == 'r':
            top = n - 1
            bottom = (params[1] or self.rows) - 1 if len(params) > 1 else self.rows - 1
            if 0 <= top < bottom < self.rows:
                self.top, self.bottom = top, bottom
                self.home()
        elif final == 'g':
            if params[0] == 0:
                self.tabs.discard(self.x)
            elif params[0] == 3:
                self.tabs.clear()
        elif final == 'c' and params[0] == 0:
            self.send(b'\x1b[?1;2c')
        elif final == 'n':
            if params[0] == 5:
                self.send(b'\x1b[0n')
            elif params[0] == 6:
                row = self.y - (self.top if self.origin else 0) + 1
                self.send(f'\x1b[{row};{self.x+1}R'.encode('ascii'))
        elif final == 's':
            self.save()
        elif final == 'u':
            self.restore()

    def key(self, name, text='', control=False):
        name = {'KP_Insert': 'KP_0', 'KP_End': 'KP_1', 'KP_Down': 'KP_2',
                'KP_Next': 'KP_3', 'KP_Left': 'KP_4', 'KP_Begin': 'KP_5',
                'KP_Right': 'KP_6', 'KP_Home': 'KP_7', 'KP_Up': 'KP_8',
                'KP_Prior': 'KP_9', 'KP_Delete': 'KP_Decimal'}.get(name, name)
        if name in ('Up', 'Down', 'Right', 'Left'):
            return b'\x1b' + (b'O' if self.cursor_keys else b'[') + {
                'Up': b'A', 'Down': b'B', 'Right': b'C', 'Left': b'D'}[name]
        if name in ('F1', 'F2', 'F3', 'F4'):
            return b'\x1bO' + bytes([ord('P') + int(name[1:]) - 1])
        keypad = {'KP_0': ('0', 'p'), 'KP_1': ('1', 'q'), 'KP_2': ('2', 'r'),
                  'KP_3': ('3', 's'), 'KP_4': ('4', 't'), 'KP_5': ('5', 'u'),
                  'KP_6': ('6', 'v'), 'KP_7': ('7', 'w'), 'KP_8': ('8', 'x'),
                  'KP_9': ('9', 'y'), 'KP_Decimal': ('.', 'n'),
                  'KP_Separator': (',', 'l'), 'KP_Subtract': ('-', 'm'), 'KP_Enter': ('\r', 'M')}
        if name in keypad:
            numeric, application = keypad[name]
            return ('\x1bO' + application if self.keypad else numeric).encode('ascii')
        if control:
            char = (text or name).upper()
            if len(char) == 1 and 64 <= ord(char) <= 95:
                return bytes([ord(char) & 31])
            if name in ('space', '2'):
                return b'\0'
        if name == 'Return':
            return b'\r\n' if self.newline else b'\r'
        if name in ('BackSpace', 'Delete'):
            return b'\x7f'
        if name == 'Escape':
            return b'\x1b'
        if name == 'Tab':
            return b'\t'
        return text.encode('ascii', errors='ignore')
