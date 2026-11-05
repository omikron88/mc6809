"""Run with python -m zeta2. GPL-3.0; see LICENSE."""
import argparse
from contextlib import ExitStack
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import time

from .machine import Zeta2
from .floppy import Disk
from .demo import demo_rom


class Terminal:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.fd = None
        self.saved = None
        self.eof = False

    def __enter__(self):
        if not self.enabled:
            return self
        if os.name == 'posix':
            import termios
            import tty
            self.fd = sys.stdin.fileno()
            if os.isatty(self.fd):
                self.saved = termios.tcgetattr(self.fd)
                tty.setraw(self.fd)
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)

    def poll(self):
        if not self.enabled or self.eof:
            return b''
        if os.name == 'nt':
            import msvcrt
            data = bytearray()
            while msvcrt.kbhit():
                c = msvcrt.getwch()
                if c in ('\x00', '\xe0'):
                    msvcrt.getwch()
                    continue
                data.extend(c.encode('latin-1', errors='replace'))
            return bytes(data)
        import select
        if select.select([self.fd], [], [], 0)[0]:
            data = os.read(self.fd, 4096)
            self.eof = not data
            return data
        return b''


def atomic_write(path, data):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_bytes(data)
    temp.replace(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Zeta SBC V2 emulator, without ParPortProp (GPL-3.0)')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--rom', type=Path, help='raw ROM image, max. 512 KiB')
    source.add_argument('--demo', action='store_true', help='built-in UART echo demonstration')
    parser.add_argument('--hz', type=int, default=8_000_000, help='emulated CPU clock (default: 8000000)')
    parser.add_argument('--cycles', type=int, help='stop after this many T-states (may overshoot by one instruction)')
    parser.add_argument('--stop-on-halt', action='store_true')
    parser.add_argument('--realtime', action='store_true', help='limit execution speed to --hz')
    parser.add_argument('--disk-a', type=Path)
    parser.add_argument('--disk-b', type=Path)
    parser.add_argument('--disk-write', action='store_true', help='allow and save writes to supplied disk images')
    parser.add_argument('--ram', type=Path, help='load/save battery-backed 512 KiB SRAM')
    parser.add_argument('--rtc-state', type=Path, help='load/save RTC registers and 31 bytes RAM')
    parser.add_argument('--rtc-time', type=datetime.fromisoformat, help='initial RTC local time, e.g. 2026-11-05T12:00:00')
    parser.add_argument('--input', type=Path, help='enqueue bytes from file before execution')
    parser.add_argument('--headless', action='store_true', help='do not read terminal input')
    parser.add_argument('--vt100', action='store_true', help='open a VT100 terminal window connected to UART (requires Tk)')
    parser.add_argument('--trace-io', type=Path, help='write I/O transactions to file')
    args = parser.parse_args(argv)
    if args.vt100 and args.headless:
        parser.error('--vt100 cannot be combined with --headless')
    if args.hz <= 0 or args.cycles is not None and args.cycles < 0:
        parser.error('--hz must be positive and --cycles nonnegative')
    if args.rtc_time and args.rtc_time.tzinfo is not None:
        parser.error('--rtc-time must be a local date/time without timezone')
    paths = [p.resolve() for p in [args.rom, args.disk_a, args.disk_b, args.ram,
                                  args.rtc_state, args.input, args.trace_io] if p]
    if len(paths) != len(set(paths)):
        parser.error('ROM, disk, state, input and trace paths must be distinct')
    machine = None
    try:
        rom = demo_rom(vt100=args.vt100) if args.demo else args.rom.read_bytes()
        disks = [Disk(p.read_bytes(), writable=args.disk_write) if p else None for p in (args.disk_a, args.disk_b)]
        with ExitStack() as stack:
            window = None
            if args.vt100:
                from .vt100_gui import VT100Window
                window = stack.enter_context(VT100Window())
            trace_file = stack.enter_context(args.trace_io.open('w')) if args.trace_io else None
            def trace(direction, port, value):
                trace_file.write(f'{machine.cpu.cycles:12d} {direction:3s} {port:04X} {value:02X}\n')
            def transmit(value):
                if window:
                    window.feed(value)
                else:
                    sys.stdout.buffer.write(bytes([value]))
                    sys.stdout.buffer.flush()
            machine = Zeta2(rom, cpu_hz=args.hz, transmit=transmit, drives=disks,
                            rtc_now=args.rtc_time, trace=trace if trace_file else None)
            if args.ram and args.ram.exists():
                data = args.ram.read_bytes()
                if len(data) != len(machine.ram):
                    raise ValueError('SRAM image must be exactly 524288 bytes')
                machine.ram[:] = data
            if args.rtc_state and args.rtc_state.exists():
                state = json.loads(args.rtc_state.read_text())
                machine.rtc.base = datetime.fromisoformat(state['time'])
                machine.rtc.halted = bool(state['halted'])
                machine.rtc.hour12 = bool(state.get('hour12', False))
                machine.rtc.wp = int(state['wp']) & 128
                machine.rtc.trickle = int(state['trickle']) & 255
                data = bytes.fromhex(state['ram'])
                if len(data) != 31:
                    raise ValueError('RTC RAM must be exactly 31 bytes')
                machine.rtc.ram[:] = data
                if args.rtc_time:
                    machine.rtc.base = args.rtc_time
            if args.input:
                machine.uart.feed(args.input.read_bytes())
            terminal = window or stack.enter_context(Terminal(not args.headless))
            print('Zeta2 Python | GPL-3.0, bez zaruky; viz LICENSE | Ctrl-] = konec', file=sys.stderr)
            started = time.monotonic()
            try:
                while args.cycles is None or machine.cpu.cycles < args.cycles:
                    data = terminal.poll()
                    if window and window.closed:
                        break
                    if b'\x1d' in data:
                        machine.uart.feed(data.split(b'\x1d', 1)[0])
                        break
                    machine.uart.feed(data)
                    budget = 4096 if args.cycles is None else min(4096, args.cycles - machine.cpu.cycles)
                    machine.run(budget, stop_on_halt=args.stop_on_halt)
                    if args.stop_on_halt and machine.cpu.halted:
                        break
                    if args.realtime:
                        delay = machine.cpu.cycles / args.hz - (time.monotonic() - started)
                        if delay > 0:
                            time.sleep(min(delay, 0.02))
            except KeyboardInterrupt:
                pass
            finally:
                if window and not window.closed:
                    window.draw(force=True)
                if args.ram:
                    atomic_write(args.ram, machine.ram)
                if args.rtc_state:
                    from datetime import timedelta
                    rtc = machine.rtc
                    state = dict(time=(rtc.base + timedelta(seconds=rtc.elapsed)).isoformat(),
                                 halted=rtc.halted, hour12=rtc.hour12, wp=rtc.wp,
                                 trickle=rtc.trickle, ram=rtc.ram.hex())
                    atomic_write(args.rtc_state, json.dumps(state, indent=2).encode())
                for path, disk in zip((args.disk_a, args.disk_b), disks):
                    if disk:
                        disk.save(path)
            print(f'\nPC={machine.cpu.r.pc:04X} cycles={machine.cpu.cycles}', file=sys.stderr)
        return 0
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print(f'zeta2: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
