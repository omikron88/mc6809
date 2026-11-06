"""Measure real instruction execution and rendering; no artificial frame delay."""
import argparse
import os
import platform
import statistics
import time

from .audio import Beeper
from .demo import demo_rom
from .machine import Spectrum48
from .video import render_rgb, DISPLAY_WIDTH, DISPLAY_HEIGHT


def workloads():
    def rom(code):
        return code.ljust(16384, b'\0')
    return [('NOP (4T)', rom(b'\0')),
            ('HALT (4T)', rom(b'\x76')),
            ('RAM/ALU loop', rom(bytes.fromhex('21 00 80 06 00 7e 3c 77 23 10 fa c3 00 00'))),
            ('Spectrum demo', demo_rom())]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frames', type=int, default=80)
    parser.add_argument('--pygame', action='store_true', help='include Pygame scaling/flip with an SDL dummy display')
    args = parser.parse_args(argv)
    if args.frames < 10:
        parser.error('--frames must be at least 10')
    pg = None
    if args.pygame:
        os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
        os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        try:
            import pygame as pg
        except ImportError:
            parser.error('install the optional spectrum/Pygame dependency first')
        pg.display.init()
        display = pg.display.set_mode((DISPLAY_WIDTH * 3, DISPLAY_HEIGHT * 3))
    print(f'{platform.python_implementation()} {platform.python_version()} / {platform.machine()}')
    print(f'{args.frames} measured frames/workload, 8 warmup frames; limit disabled')
    print(f'Budget: {Spectrum48.FRAME_CYCLES} T-states / {Spectrum48.FRAME_CYCLES / Spectrum48.CPU_HZ * 1000:.3f} ms')
    print('Rendering: RGB + beeper PCM' + (' + Pygame 3x scale/flip (dummy SDL)' if pg else ''))
    print('workload          CPU median   total median  total p95    max      CPU MHz   >budget')
    try:
        for name, rom in workloads():
            machine = Spectrum48(rom)
            audio = Beeper()
            cpu_times, total_times = [], []
            cycles, cpu_seconds = 0, 0.0
            for frame in range(args.frames + 8):
                start = time.perf_counter()
                before = machine.cpu.cycles
                machine.run_frame()
                after_cpu = time.perf_counter()
                rgb = render_rgb(machine)
                audio.render(machine)
                if pg:
                    image = pg.image.frombuffer(rgb, (DISPLAY_WIDTH, DISPLAY_HEIGHT), 'RGB').convert()
                    pg.transform.scale(image, display.get_size(), display)
                    pg.display.flip()
                    pg.event.pump()
                end = time.perf_counter()
                if frame >= 8:
                    cpu_times.append((after_cpu - start) * 1000)
                    total_times.append((end - start) * 1000)
                    cpu_seconds += after_cpu - start
                    cycles += machine.cpu.cycles - before
            p95 = sorted(total_times)[int((len(total_times) - 1) * 0.95)]
            late = sum(t > machine.FRAME_CYCLES / machine.CPU_HZ * 1000 for t in total_times)
            print(f'{name:17s} {statistics.median(cpu_times):8.2f} ms {statistics.median(total_times):8.2f} ms'
                  f' {p95:8.2f} ms {max(total_times):7.2f} ms {cycles/cpu_seconds/1e6:7.2f}  {late}/{args.frames}')
    finally:
        if pg:
            pg.quit()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
