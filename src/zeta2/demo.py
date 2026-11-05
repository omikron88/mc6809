"""Small original boot ROM: configure MMU and UART, print banner, echo input."""


def demo_rom(vt100=False):
    code = bytearray([0xF3])  # DI
    for port, value in [(0x78, 0), (0x79, 32), (0x7A, 33), (0x7B, 34),
                        (0x7C, 1), (0x6B, 0x80), (0x68, 1), (0x69, 0),
                        (0x6B, 3), (0x69, 0), (0x6A, 7), (0x6C, 3)]:
        code.extend([0x3E, value, 0xD3, port])
    code.extend([0x31, 0xFF, 0xFF])  # LD SP,FFFFh
    message = b'Zeta2 Python - UART 16550\r\nMMU: ROM + 48 KiB RAM; no ParPortProp\r\n> '
    if vt100:
        message = (b'\x1b[2J\x1b[H\x1b[1;7m ZETA2 / VT100 / UART 16550 \x1b[0m\r\n'
                   b'\x1b(0l' + b'q' * 58 + b'k\r\n'
                   b'x\x1b(B  Python Z80 emulator - no ParPortProp'
                   b'\x1b[3;60H\x1b(0x\r\n'
                   b'm' + b'q' * 58 + b'j\x1b(B\r\n\r\n'
                   b'\x1b[4mKeyboard echo\x1b[0m  |  arrows send VT100 sequences\r\n'
                   b'MMU: ROM + 48 KiB RAM\r\n\r\n> ')
    for value in message:
        code.extend([0x3E, value, 0xD3, 0x68])
    loop = len(code)
    # IN A,(LSR); AND 1; JR Z,loop; IN A,(RBR); OUT (THR),A; JP loop
    code.extend([0xDB, 0x6D, 0xE6, 1, 0x28, 0xFA, 0xDB, 0x68, 0xD3, 0x68,
                 0xC3, loop & 255, loop >> 8])
    return bytes(code).ljust(512 * 1024, b'\xFF')
