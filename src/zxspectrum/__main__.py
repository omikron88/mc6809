"""Pygame frontend: python -m zxspectrum --demo or --rom 48.rom. GPL-3.0."""
import argparse
import os
from pathlib import Path
import sys
import time

from .audio import Beeper
from .demo import demo_rom
from .machine import Spectrum48
from .video import DISPLAY_WIDTH, DISPLAY_HEIGHT, render_rgb


def keymap(pg):
    result = {getattr(pg, 'K_' + c): (c.upper(),) for c in 'abcdefghijklmnopqrstuvwxyz0123456789'}
    result.update({pg.K_LSHIFT: ('CAPS SHIFT',), pg.K_RSHIFT: ('CAPS SHIFT',),
                   pg.K_LCTRL: ('SYMBOL SHIFT',), pg.K_RCTRL: ('SYMBOL SHIFT',),
                   pg.K_RETURN: ('ENTER',), pg.K_KP_ENTER: ('ENTER',), pg.K_SPACE: ('SPACE',),
                   pg.K_BACKSPACE: ('CAPS SHIFT', '0'), pg.K_ESCAPE: ('CAPS SHIFT', 'SPACE'),
                   pg.K_LEFT: ('CAPS SHIFT', '5'), pg.K_DOWN: ('CAPS SHIFT', '6'),
                   pg.K_UP: ('CAPS SHIFT', '7'), pg.K_RIGHT: ('CAPS SHIFT', '8'),
                   pg.K_COMMA: ('SYMBOL SHIFT', 'N'), pg.K_PERIOD: ('SYMBOL SHIFT', 'M'),
                   pg.K_MINUS: ('SYMBOL SHIFT', 'J'), pg.K_EQUALS: ('SYMBOL SHIFT', 'L'),
                   pg.K_SLASH: ('SYMBOL SHIFT', 'V'), pg.K_SEMICOLON: ('SYMBOL SHIFT', 'O'),
                   pg.K_QUOTE: ('SYMBOL SHIFT', 'P')})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='Bare ZX Spectrum 48K using the shared Z80 core and Pygame')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--rom', type=Path, help='exactly 16 KiB Spectrum 48K ROM (not supplied)')
    source.add_argument('--demo', action='store_true', help='original colour/keyboard demo ROM')
    parser.add_argument('--scale', type=int, default=3, choices=range(1, 7), metavar='1..6')
    parser.add_argument('--frames', type=int, help='exit after a fixed positive number of frames')
    parser.add_argument('--mute', action='store_true', help='do not initialize audio')
    parser.add_argument('--no-limit', action='store_true', help='run at maximum host speed')
    parser.add_argument('--screenshot', type=Path, help='save final 320x256 display as PNG')
    args = parser.parse_args(argv)
    if args.frames is not None and args.frames <= 0:
        parser.error('--frames must be positive')
    try:
        machine = Spectrum48(demo_rom() if args.demo else args.rom.read_bytes())
    except (OSError, ValueError) as exc:
        print(f'zxspectrum: {exc}', file=sys.stderr)
        return 1
    os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
    try:
        import pygame as pg
    except ImportError:
        print('zxspectrum: install Pygame with python -m pip install -e ".[spectrum]"', file=sys.stderr)
        return 1
    try:
        pg.display.init()
        display = pg.display.set_mode((DISPLAY_WIDTH * args.scale, DISPLAY_HEIGHT * args.scale))
        pg.display.set_caption('ZX Spectrum 48K | Z80 + Pygame | F12 reset | F10 exit')
        beeper = Beeper()
        channel = None
        if not args.mute:
            try:
                pg.mixer.init(frequency=beeper.rate, size=-16, channels=1, buffer=1024)
                channel = pg.mixer.Channel(0)
            except pg.error as exc:
                print(f'zxspectrum: audio disabled ({exc})', file=sys.stderr)
        mapping = keymap(pg)
        held = {}
        running, frames = True, 0
        deadline = time.perf_counter()
        image = None
        print('ZX Spectrum 48K | GPL-3.0, bez zaruky; viz LICENSE | F10 konec, F12 reset', file=sys.stderr)
        while running and (args.frames is None or frames < args.frames):
            for event in pg.event.get():
                if event.type == pg.QUIT:
                    running = False
                elif event.type == pg.WINDOWFOCUSLOST:
                    held.clear()
                elif event.type == pg.KEYDOWN:
                    if event.key == pg.K_F10:
                        running = False
                    elif event.key == pg.K_F12:
                        machine.reset()
                        held.clear()
                        beeper = Beeper()
                        if channel:
                            channel.stop()
                    elif event.key in mapping:
                        held[event.key] = mapping[event.key]
                elif event.type == pg.KEYUP:
                    held.pop(event.key, None)
            machine.keys = {name for keys in held.values() for name in keys}
            if not running:
                break
            machine.run_frame()
            rgb = render_rgb(machine)
            image = pg.image.frombuffer(rgb, (DISPLAY_WIDTH, DISPLAY_HEIGHT), 'RGB').convert()
            pg.transform.scale(image, display.get_size(), display)
            pg.display.flip()
            if channel:
                pcm = beeper.render(machine)
                if pcm:
                    sound = pg.mixer.Sound(buffer=pcm)
                    if not channel.get_busy():
                        channel.play(sound)
                    elif channel.get_queue() is None:
                        channel.queue(sound)
            else:
                machine.beeper_events.clear()
            frames += 1
            if not args.no_limit:
                deadline += machine.FRAME_CYCLES / machine.CPU_HZ
                delay = deadline - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                else:
                    deadline = time.perf_counter()
        if args.screenshot:
            if image is None:
                rgb = render_rgb(machine)
                image = pg.image.frombuffer(rgb, (DISPLAY_WIDTH, DISPLAY_HEIGHT), 'RGB')
            pg.image.save(image, str(args.screenshot))
        return 0
    except (OSError, pg.error) as exc:
        print(f'zxspectrum: {exc}', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        pg.quit()


if __name__ == '__main__':
    raise SystemExit(main())
