import unittest

from zeta2 import Zeta2
from zeta2.demo import demo_rom
from zeta2.vt100 import VT100, Cell


class VT100Tests(unittest.TestCase):
    def test_cr_lf_backspace_and_tabs(self):
        t = VT100()
        t.feed(b'abc\rX\nY\bZ\t!')
        self.assertEqual(t.lines[0][:3], 'Xbc')
        self.assertEqual(t.lines[1][1], 'Z')
        self.assertEqual(t.lines[1][8], '!')

    def test_fragmented_sequences_and_cursor_defaults(self):
        t = VT100()
        for byte in b'\x1b[12;34H*\x1b[2A\x1b[D!':
            t.feed(byte)
        self.assertEqual(t.screen[11][33].char, '*')
        self.assertEqual(t.screen[9][33].char, '!')
        t.feed(b'\x1b[;H')
        self.assertEqual((t.x, t.y), (0, 0))

    def test_erase_display_keeps_cursor(self):
        t = VT100()
        t.feed(b'abcd\x1b[2;3Hxy\x1b[1J')
        self.assertEqual(t.lines[0], ' ' * 80)
        self.assertEqual(t.lines[1], ' ' * 80)
        self.assertEqual((t.x, t.y), (4, 1))
        t.feed(b'xyz\x1b[2J')
        self.assertTrue(all(line == ' ' * 80 for line in t.lines))
        self.assertEqual((t.x, t.y), (7, 1))

    def test_erase_line_modes(self):
        t = VT100()
        t.feed(b'abcdef\x1b[1;4H\x1b[K')
        self.assertEqual(t.lines[0][:6], 'abc   ')
        t.feed(b'\x1b[1K')
        self.assertEqual(t.lines[0], ' ' * 80)
        t.feed(b'abc\x1b[2K')
        self.assertEqual(t.lines[0], ' ' * 80)

    def test_autowrap_is_delayed_and_sgr_preserves_it(self):
        t = VT100()
        t.feed(b'x' * 80)
        self.assertEqual((t.x, t.y), (79, 0))
        t.feed(b'\x1b[1mY')
        self.assertEqual(t.screen[1][0], Cell('Y', bold=True))
        t.feed(b'\x1b[?7l\x1b[1;80HAB')
        self.assertEqual(t.screen[0][79].char, 'B')
        self.assertEqual(t.y, 0)

    def test_scroll_region_origin_and_reverse_index(self):
        t = VT100()
        for y in range(24):
            t.feed(f'\x1b[{y+1};1H{chr(65+y)}'.encode())
        t.feed(b'\x1b[3;5r\x1b[?6h\x1b[3;1H\n')
        self.assertEqual(t.lines[0][0], 'A')
        self.assertEqual(t.lines[2][0], 'D')
        self.assertEqual(t.lines[3][0], 'E')
        self.assertEqual(t.lines[4][0], ' ')
        self.assertEqual(t.lines[5][0], 'F')
        t.feed(b'\x1b[H\x1bM')
        self.assertEqual(t.lines[2][0], ' ')
        self.assertEqual(t.lines[3][0], 'D')
        self.assertEqual(t.y, 2)

    def test_attributes_and_save_restore(self):
        t = VT100()
        t.feed(b'\x1b[1;4;5;7m\x1b[5;7H\x1b7\x1b[0m\x1b[Hq\x1b8X')
        self.assertEqual(t.screen[4][6], Cell('X', True, True, True, True))
        self.assertEqual(t.screen[0][0], Cell('q'))
        t.feed(b'\x1b[22;24;25;27mY')
        self.assertEqual(t.screen[4][7], Cell('Y'))

    def test_graphics_and_shift_sets(self):
        t = VT100()
        t.feed(b'\x1b(0lqk\x1b(Babc\x1b)0\x0ex\x0fz')
        self.assertEqual(t.lines[0][:8], '┌─┐abc│z')
        t.feed(b'\x1b(A#')
        self.assertEqual(t.screen[0][8].char, '£')

    def test_tab_clear_and_set(self):
        t = VT100()
        t.feed(b'\x1b[3g\x1b[1;5H\x1bH\r\tX')
        self.assertEqual(t.screen[0][4].char, 'X')
        t.feed(b'\b\x1b[g\r\t')
        self.assertEqual(t.x, 79)

    def test_responses_and_origin_coordinates(self):
        output = bytearray()
        t = VT100(send=output.extend)
        t.feed(b'\x1b[c\x1b[5n\x1b[7;8H\x1b[6n')
        self.assertEqual(output, b'\x1b[?1;2c\x1b[0n\x1b[7;8R')
        output.clear()
        t.feed(b'\x1b[3;20r\x1b[?6h\x1b[6n')
        self.assertEqual(output, b'\x1b[1;1R')

    def test_keyboard_modes_and_control(self):
        t = VT100()
        self.assertEqual(t.key('Up'), b'\x1b[A')
        t.feed(b'\x1b[?1h\x1b=')
        self.assertEqual(t.key('Left'), b'\x1bOD')
        self.assertEqual(t.key('KP_3'), b'\x1bOs')
        self.assertEqual(t.key('F4'), b'\x1bOS')
        self.assertEqual(t.key('c', 'c', True), b'\x03')
        self.assertEqual(t.key('Return'), b'\r')
        self.assertEqual(t.key('BackSpace'), b'\x7f')
        t.feed(b'\x1b[20h')
        self.assertEqual(t.key('Return'), b'\r\n')

    def test_reset_and_column_switch(self):
        t = VT100()
        t.feed(b'abc\x1b[?3h')
        self.assertEqual(t.columns, 132)
        self.assertTrue(all(len(line) == 132 for line in t.screen))
        t.feed(b'\x1b[?5h\x1b[?25l\x1bc')
        self.assertEqual(t.columns, 80)
        self.assertFalse(t.reverse_screen)
        self.assertTrue(t.cursor_visible)

    def test_cancel_and_oversize_sequence_recovery(self):
        t = VT100()
        t.feed(b'\x1b[12;\x18OK')
        self.assertEqual(t.lines[0][:2], 'OK')
        t.feed(b'\x1b[' + b'9' * 200 + b'\x1b[H!')
        self.assertEqual(t.screen[0][0].char, '!')

    def test_uart_link_executes_z80_and_sends_query_reply(self):
        terminal = VT100()
        # ROM emits clear, position, reverse video and a cursor query via OUT.
        code = bytearray()
        for byte in b'\x1b[2J\x1b[4;10H\x1b[7mZETA\x1b[0m\x1b[6n':
            code.extend([0x3E, byte, 0xD3, 0x68])
        code.append(0x76)
        machine = Zeta2(code, transmit=terminal.feed)
        terminal.send = machine.uart.feed
        machine.run(10000, stop_on_halt=True)
        self.assertEqual(terminal.lines[3][9:13], 'ZETA')
        self.assertTrue(terminal.screen[3][9].reverse)
        reply = bytes(machine.input(0x68) for _ in range(7))
        self.assertEqual(reply, b'\x1b[4;14R')
        machine.uart.feed(terminal.key('Down'))
        self.assertEqual(bytes(machine.input(0x68) for _ in range(3)), b'\x1b[B')

    def test_graphical_demo_rom_outputs_vt100_screen(self):
        terminal = VT100()
        machine = Zeta2(demo_rom(vt100=True), transmit=terminal.feed)
        machine.run(30000)
        self.assertIn('ZETA2 / VT100', terminal.lines[0])
        self.assertEqual(terminal.screen[1][0].char, '┌')
        self.assertEqual(terminal.screen[3][59].char, '┘')
        self.assertTrue(terminal.screen[5][0].underline)
        machine.uart.feed(b'OK')
        machine.run(5000)
        self.assertIn('> OK', terminal.lines[8])


if __name__ == '__main__':
    unittest.main()
