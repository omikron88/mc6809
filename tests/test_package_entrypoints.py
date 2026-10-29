"""Public exports and command-line entry points of both installed packages."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class PackageEntrypoints(unittest.TestCase):
    def test_public_exports_and_inert_main_import(self):
        for name in ('mc6809', 'z80'):
            with self.subTest(package=name):
                package = importlib.import_module(name)
                for exported in package.__all__:
                    self.assertIsNotNone(getattr(package, exported))
                main = importlib.import_module(name + '.__main__').main
                self.assertTrue(callable(main))
                with self.assertRaises(AttributeError):
                    getattr(package, 'missing_attribute')

    def test_cli_modules(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTHONPATH=str(root / 'src'), PYTHONWARNINGS='error')
        cases = (
            ('mc6809', 'lda #$2a\n', bytes.fromhex('86 2a')),
            ('z80', 'ld a,$2a\n', bytes.fromhex('3e 2a')),
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'program.asm'
            output = Path(directory) / 'program.bin'
            for name, program, expected in cases:
                source.write_text(program)
                assembler = 'asm6809' if name == 'mc6809' else 'assembler'
                for module in (name, name + '.' + assembler):
                    with self.subTest(module=module):
                        output.unlink(missing_ok=True)
                        result = subprocess.run(
                            [sys.executable, '-m', module, str(source), '-o', str(output), '--trim'],
                            cwd=directory, env=env, capture_output=True, text=True,
                        )
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stderr, '')
                        self.assertEqual(output.read_bytes(), expected)
                cli = importlib.import_module(name + '.' + assembler).main
                self.assertEqual(cli([str(source), '-o', str(output), '--trim']), 0)

    def test_legacy_6809_script(self):
        script = Path(__file__).resolve().parents[1] / 'src/mc6809/asm6809.py'
        result = subprocess.run([sys.executable, str(script), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--cpu', result.stdout)


if __name__ == '__main__':
    unittest.main()
