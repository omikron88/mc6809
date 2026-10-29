"""Bus callback routing for MREQ+M1 and IORQ+M1."""
import unittest
from z80 import Z80


class BusCallbacks(unittest.TestCase):
    def make(self, code):
        memory = bytearray(65536)
        code = bytes.fromhex(code)
        memory[:len(code)] = code
        events = []
        def read(address):
            events.append(('read', address))
            return memory[address]
        def fetch(address):
            events.append(('fetch', address))
            return memory[address]
        def write(address, value):
            events.append(('write', address, value))
            memory[address] = value
        def intack():
            events.append(('intack',))
            return 0x10
        return Z80(read, write, fetch=fetch, intack=intack), memory, events

    def test_fetch_supplies_opcode_and_read_supplies_operands(self):
        cpu, memory, events = self.make('00 2a')
        cpu.fetch = lambda address: events.append(('fetch', address)) or 0x13e
        cpu.step()
        self.assertEqual(cpu.r.a, 42)
        self.assertEqual(events, [('fetch', 0), ('read', 1)])
        self.assertEqual(cpu.r.r, 1)

    def test_prefixes_and_index_cb_non_m1_opcode(self):
        for code, expected in (
            ('cb 00', [('fetch', 0), ('fetch', 1)]),
            ('ed 44', [('fetch', 0), ('fetch', 1)]),
            ('dd fd 21 34 12', [('fetch', 0), ('fetch', 1), ('fetch', 2), ('read', 3), ('read', 4)]),
            ('dd cb 02 46', [('fetch', 0), ('fetch', 1), ('read', 2), ('read', 3), ('read', 0x8002)]),
        ):
            with self.subTest(code=code):
                cpu, memory, events = self.make(code)
                cpu.r.ix = 0x8000
                cpu.step()
                self.assertEqual(events, expected)
                self.assertEqual(cpu.r.r, sum(e[0] == 'fetch' for e in expected))

    def test_im0_reads_opcode_from_intack(self):
        cpu, memory, events = self.make('34 12')
        cpu.intack = lambda: events.append(('intack',)) or 0x1cd
        cpu.iff1 = True
        cpu.irq(data=0xff)  # callback overrides the legacy data parameter
        cpu.r.sp = 0x8000
        self.assertEqual(cpu.step(), 19)
        self.assertEqual(cpu.r.pc, 0x1234)
        self.assertEqual(events, [('intack',), ('read', 0), ('read', 1), ('write', 0x7fff, 0), ('write', 0x7ffe, 2)])
        self.assertEqual(cpu.r.r, 1)

    def test_im0_injected_prefix_uses_memory_fetch_for_next_opcode(self):
        cpu, memory, events = self.make('44')
        cpu.intack = lambda: events.append(('intack',)) or 0xed
        cpu.r.a = 1
        cpu.iff1 = True
        cpu.irq()
        self.assertEqual(cpu.step(), 10)
        self.assertEqual(cpu.r.a, 255)
        self.assertEqual(events, [('intack',), ('fetch', 0)])
        self.assertEqual(cpu.r.r, 2)

    def test_im1_acknowledges_but_ignores_bus_data(self):
        cpu, memory, events = self.make('00')
        cpu.im = 1
        cpu.iff1 = True
        cpu.irq()
        self.assertEqual(cpu.step(), 13)
        self.assertEqual(cpu.r.pc, 0x38)
        self.assertEqual(events[0], ('intack',))
        self.assertEqual(sum(e[0] == 'intack' for e in events), 1)
        self.assertFalse(any(e[0] in ('read', 'fetch') for e in events))

    def test_im2_vector_reads_are_not_opcode_fetches(self):
        cpu, memory, events = self.make('00')
        cpu.im = 2
        cpu.r.i = 0x80
        cpu.r.sp = 0x9000
        memory[0x8010:0x8012] = bytes.fromhex('34 12')
        cpu.iff1 = True
        cpu.irq(data=0xff)
        self.assertEqual(cpu.step(), 19)
        self.assertEqual(cpu.r.pc, 0x1234)
        self.assertEqual(events, [('intack',), ('write', 0x8fff, 0), ('write', 0x8ffe, 0), ('read', 0x8010), ('read', 0x8011)])

    def test_no_intack_for_masked_or_ei_delayed_int(self):
        cpu, memory, events = self.make('fb 00 00')
        cpu.irq()
        cpu.step()
        cpu.step()
        self.assertEqual(events, [('fetch', 0), ('fetch', 1)])
        cpu.step()
        self.assertEqual(events[2], ('intack',))

    def test_halt_and_nmi_fetch_without_pc_increment(self):
        cpu, memory, events = self.make('76 00')
        cpu.step()
        cpu.step()
        self.assertEqual(events, [('fetch', 0), ('fetch', 1)])
        self.assertEqual(cpu.r.pc, 1)
        cpu.nmi()
        cpu.step()
        self.assertEqual(events[2], ('fetch', 1))
        self.assertFalse(any(e[0] == 'intack' for e in events))
        self.assertEqual(cpu.r.pc, 0x66)
        self.assertEqual(cpu.r.r, 3)

    def test_legacy_callbacks_and_reset(self):
        memory = bytearray(65536)
        memory[:2] = bytes.fromhex('3e 2a')
        cpu = Z80(memory.__getitem__, memory.__setitem__)
        cpu.step()
        self.assertEqual(cpu.r.a, 42)
        cpu.iff1 = True
        cpu.irq(data=0xcf)
        self.assertEqual(cpu.step(), 13)
        self.assertEqual(cpu.r.pc, 8)
        cpu.reset()
        self.assertEqual(cpu.intack(), 255)
        cpu.step()
        self.assertEqual(cpu.r.a, 42)

    def test_fetch_address_wrap(self):
        cpu, memory, events = self.make('44')
        cpu.r.pc = 65535
        memory[65535] = 0xed
        cpu.step()
        self.assertEqual(events, [('fetch', 65535), ('fetch', 0)])
        self.assertEqual(cpu.r.pc, 1)


if __name__ == '__main__':
    unittest.main()
