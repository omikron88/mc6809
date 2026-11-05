"""Tk screen connected to UART by the CLI; Tk is loaded only in GUI mode."""
import time
from .vt100 import VT100


class VT100Window:
    def __init__(self):
        self.pending = bytearray()
        self.closed = False
        self.model = VT100(send=self.pending.extend, bell=self.bell)
        self.root = None
        self.last_draw = 0
        self.last_blink = time.monotonic()
        self.blink_on = True
        self.cache = {}
        self.items = {}
        self.dimensions = None

    def __enter__(self):
        try:
            import tkinter as tk
            from tkinter import font
        except ImportError as exc:
            raise RuntimeError(f'VT100 needs Tk and a graphical display: {exc}') from exc
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise RuntimeError(f'VT100 needs Tk and a graphical display: {exc}') from exc
        self.root.title('Zeta2 — VT100 / UART 16550')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.resizable(False, False)
        self.fonts = {(bold, underline): font.Font(family='DejaVu Sans Mono', size=13,
                      weight='bold' if bold else 'normal', underline=underline)
                      for bold in (False, True) for underline in (False, True)}
        self.cell_width = max(f.measure('M') for f in self.fonts.values())
        self.cell_height = max(f.metrics('linespace') for f in self.fonts.values()) + 2
        self.canvas = tk.Canvas(self.root, background='#07100b', highlightthickness=0)
        self.canvas.pack()
        self.status = tk.Label(self.root, text='80 × 24  |  UART 16550  |  Ctrl-] konec  |  Ctrl-Shift-V vložit',
                               anchor='w', background='#14251b', foreground='#a5cbb0')
        self.status.pack(fill='x')
        self.root.bind('<KeyPress>', self.on_key)
        self.root.bind('<Control-Shift-v>', self.paste)
        self.root.bind('<Control-Shift-V>', self.paste)
        self.root.bind('<Shift-Insert>', self.paste)
        self.root.bind('<FocusIn>', lambda event: self.invalidate())
        self.root.bind('<FocusOut>', lambda event: self.invalidate())
        self.canvas.focus_set()
        self.draw(force=True)
        self.root.update()
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if not self.closed:
            self.closed = True
            if self.root is not None:
                self.root.destroy()

    def bell(self):
        if self.root is not None and not self.closed:
            self.root.bell()

    def invalidate(self):
        self.cache.clear()
        self.model.dirty = True

    def on_key(self, event):
        if event.state & 4 and event.keysym == 'bracketright':
            self.close()
            return 'break'
        self.pending.extend(self.model.key(event.keysym, event.char, control=bool(event.state & 4)))
        return 'break'

    def paste(self, event=None):
        import tkinter as tk
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return 'break'
        text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\n', '\r')
        self.pending.extend(text.encode('ascii', errors='ignore'))
        return 'break'

    def feed(self, value):
        self.model.feed(value)

    def poll(self):
        if not self.closed:
            now = time.monotonic()
            if now - self.last_blink >= 0.5:
                self.blink_on = not self.blink_on
                self.last_blink = now
                self.model.dirty = True
            if now - self.last_draw >= 1 / 30:
                self.draw()
                self.root.update()
                self.last_draw = now
        data = bytes(self.pending)
        self.pending.clear()
        return data

    def draw(self, force=False):
        if self.closed or not (force or self.model.dirty):
            return
        m, cw, ch = self.model, self.cell_width, self.cell_height
        if self.dimensions != (m.columns, m.rows):
            self.canvas.delete('all')
            self.items.clear()
            self.cache.clear()
            self.canvas.configure(width=m.columns * cw + 16, height=m.rows * ch + 16)
            self.status.configure(text=f'{m.columns} × {m.rows}  |  UART 16550  |  Ctrl-] konec  |  Ctrl-Shift-V vložit')
            self.dimensions = (m.columns, m.rows)
        green, dark = '#8fffb0', '#07100b'
        for y, line in enumerate(m.screen):
            for x, cell in enumerate(line):
                inverse = cell.reverse ^ m.reverse_screen
                fg, bg = (dark, green) if inverse else (green, dark)
                char = ' ' if cell.blink and not self.blink_on else cell.char
                state = (char, cell.bold, cell.underline, fg, bg)
                key = (x, y)
                if self.cache.get(key) == state:
                    continue
                px, py = 8 + x * cw, 8 + y * ch
                if key not in self.items:
                    rectangle = self.canvas.create_rectangle(px, py, px + cw, py + ch, width=0)
                    text = self.canvas.create_text(px, py, anchor='nw')
                    self.items[key] = rectangle, text
                rectangle, text = self.items[key]
                self.canvas.itemconfigure(rectangle, fill=bg)
                self.canvas.itemconfigure(text, text=char, fill=fg, font=self.fonts[(cell.bold, cell.underline)])
                self.cache[key] = state
        self.canvas.delete('cursor')
        if m.cursor_visible and self.blink_on:
            px, py = 8 + m.x * cw, 8 + m.y * ch
            self.canvas.create_rectangle(px, py, px + cw - 1, py + ch - 1,
                                         outline=green, width=2, tags='cursor')
        m.dirty = False
