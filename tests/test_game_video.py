import random
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from tools.game_video_model import SRAM, Video, descriptor_address, pixel_address, palette_address

ROOT = Path(__file__).resolve().parents[1]


class GameVideoTests(unittest.TestCase):
    def fixture(self):
        ram = SRAM()
        # Distinct bank and address data; palette/descriptor writes follow this fill.
        for a in range(262144):
            ram.write(a, (a ^ (a >> 8) ^ (a >> 16)) & 255)
        for page in range(2):
            for col in range(56):
                for row in range(40):
                    ram.load(descriptor_address(page, col * 8, row * 8),
                             ((col & 3) << 6, 17 + page, 64 + row, 0))
        return ram

    def test_full_raster_two_pages_and_frame_wrap(self):
        ram = self.fixture()
        v = Video(ram)
        v.next_sample()  # discard startup sample before first descriptor
        for page in (0, 1):
            v.page = page
            # Flush a request which might have been issued before page switch.
            v.next_sample()
            seen = set()
            for _ in range(448 * 320):
                s = v.next_sample()
                seen.add((s.x, s.y))
                self.assertEqual(s.descriptor, descriptor_address(page, s.x, s.y))
                mode = tuple(ram.banks[3-i][s.descriptor >> 2] for i in range(4))
                expected = ((64 + s.y // 8 + s.y % 8) * 1024 + 17 + page + s.x % 8)
                self.assertEqual(s.address, expected)
                self.assertEqual(s.bank, 3 - expected % 4)
                self.assertEqual(s.color, ram.banks[s.bank][expected >> 2])
                self.assertEqual(s.palette, (mode[0] >> 6) * 256 + s.color)
            self.assertEqual(len(seen), 448 * 320)

    def test_every_scroll_value_crossings_and_inheritance(self):
        ram = self.fixture()
        for sy in range(16):
            for sx in range(16):
                v = Video(ram)
                v.scroll = sx | sy << 4
                v.x, v.y = 437, 315
                v.next_sample()
                for _ in range(25):
                    s = v.next_sample()
                    self.assertEqual(s.x, (v.x + sx) % 448)
                    self.assertEqual(s.y, (v.y + sy) % 320)
                    self.assertEqual(v.scroll, sx | sy << 4)

    def test_control_capture_once_and_next_request_latency(self):
        ram = self.fixture()
        # Control at invisible column 53, row 39; no automatic frame reset.
        ram.load(descriptor_address(0, 424, 312), (0x24, 19, 87, 0xff))
        v = Video(ram)
        v.x, v.y = 423, 312
        v.next_sample()
        first = v.next_sample()
        self.assertEqual((first.x, first.y), (424, 312))
        self.assertEqual(first.address, 87 * 1024 + 19)
        self.assertEqual(v.scroll, 0)
        # Every byte of the marked cell uses the OLD grid, including its tail.
        for local in range(1, 8):
            s = v.next_sample()
            self.assertEqual((s.x, s.y), (424 + local, 312))
            self.assertEqual(s.address, 87 * 1024 + 19 + local)
            self.assertEqual(v.scroll, 255 if local == 7 else 0)
        second = v.next_sample()
        self.assertEqual((second.x, second.y), (447, 7))
        self.assertEqual(v.scroll_loads, 1)
        for _ in range(1000): v.next_sample()
        self.assertEqual(v.scroll, 255)
        # A zero control loads once even though it is read eight times.
        ram.load(descriptor_address(0, 8, 0), (0x24, 0, 80, 0))
        v = Video(ram); v.x = 7
        v.next_sample()
        for _ in range(8): v.next_sample()
        self.assertEqual(v.scroll_loads, 1)
        ram.load(descriptor_address(0, 16, 0), (0x24, 0, 80, 0x21))
        for _ in range(8): v.next_sample()
        self.assertEqual(v.scroll, 0x21)

    def test_unaligned_graphics_overflow_and_all_banks(self):
        for xbase in (0, 1, 2, 3, 255, 256, 1019, 1023):
            for ybase in (0, 250, 255):
                for x in range(8):
                    for y in range(8):
                        mode = (0x20 | xbase >> 8, xbase & 255, ybase, 0)
                        expected = ((((ybase + y) % 256) * 1024) + xbase + x) % 262144
                        self.assertEqual(pixel_address(mode, x, y), expected)

    def test_control_colors_blank_interrupt_and_palette_delay(self):
        for m0 in (0x24, 0x64, 0xa4, 0xe4, 0xf4, 0xfc, 0xfd, 0xfe, 0xff):
            ram = self.fixture()
            ram.load(descriptor_address(0, 8, 0), (m0, 5, 90, 0))
            v = Video(ram); v.x = 7; v.border = 5
            v.next_sample(); s = v.next_sample()
            is_border = m0 >= 0xe0
            self.assertEqual(s.blank, m0 >= 0xfc)
            self.assertEqual(s.irq, m0 in (0xfd, 0xff))
            self.assertEqual(s.palette, 0x400 if m0 >= 0xfc else
                             0x42d if is_border else (m0 >> 6) * 256 + s.color)
            while v.phase != 0: v.step()
            self.assertEqual(v.slots[-1], (6, 'palette', palette_address(s.palette)))

    def test_sram_setup_and_cpu_slot(self):
        v = Video(self.fixture()); v.cpu_write = 0x98
        for _ in range(18): v.step()
        self.assertEqual([slot for _, slot, _ in v.slots[-6:]],
                         ['pixel', 'pixel', 'descriptor', 'descriptor', 'cpu', 'palette'])
        self.assertEqual(v.ram.banks[3][v.cpu_address >> 2], 0x98)
        # A too-slow FPGA return path still fails, despite the extra cycle.
        slow = Video(SRAM(fpga_input_delay_ns=40))
        slow.mode = (0, 1, 40, 0)
        slow.step(); slow.step()
        with self.assertRaisesRegex(RuntimeError, 'setup'): slow.step()

    def test_same_sram_word_does_not_restart_access_time(self):
        ram = SRAM(latency_ns=30)
        ram.issue(0x100, 0)
        ram.issue(0x103, 24)  # byte offset does not exist on VA pins
        self.assertEqual(ram.issued_ns, 0)
        ram.read_banks(48)
        ram.issue(0x104, 49)
        with self.assertRaisesRegex(RuntimeError, 'setup'): ram.read_banks(60)

    def test_capture_scroll_edges_and_frame_retention(self):
        ram = self.fixture()
        ram.load(descriptor_address(0, 8, 0), (0x24, 2, 3, 0x9a))
        v = Video(ram); v.x = 7
        while v.phase != 2: v.step()
        v.step()  # descriptor issued
        self.assertEqual(v.scroll, 0)
        v.step()  # CT=4 holds descriptor for a second full period
        v.step()  # all bytes captured before CPU takes bus
        self.assertEqual(v.mode, (0x24, 2, 3, 0x9a))
        self.assertEqual(v.scroll, 0)
        v.step()  # CT=6 does not apply a control inside its own cell
        self.assertEqual(v.scroll, 0)
        for _ in range(8): v.next_sample()
        self.assertEqual(v.scroll, 0x9a)
        v.x, v.y = 391, 319
        v.pending = None
        for _ in range(12): v.step()
        self.assertEqual(v.y, 0)
        self.assertEqual(v.scroll, 0x9a)

    def test_source_vcm_phase_sequence_matches_model(self):
        source = (ROOT / 'altera/acex/GAME_K50/VIDEO2.TDF').read_text()
        transitions = dict((int(a, 2), int(b)) for a, b in
                           re.findall(r'WHEN B"([01]{3})" => VCM\[2\.\.0\]\.d = (\d)', source))
        from tools.game_video_model import PHASES, VCM
        for index, phase in enumerate(PHASES):
            self.assertEqual(transitions[phase], VCM[PHASES[(index + 1) % 6]])

    def test_shared_write_and_raster_logic_unchanged(self):
        old = (ROOT / 'altera/acex/K50/VIDEO2.TDF').read_text()
        new = (ROOT / 'altera/acex/GAME_K50/VIDEO2.TDF').read_text()
        for start, end in (('--\t=== Sinc-counts', '--\t==== Video'),
                           ('\tV_WE_R\t\t= DFF', 'END GENERATE;\t-- end')):
            self.assertEqual(old[old.index(start):old.index(end)], new[new.index(start):new.index(end)])
        def cpu_slot(source):
            source = re.sub(r'--[^\n]*', '', source)
            start = source.index('CASE VCM[')
            start = source.index('WHEN 2 =>', start)
            end = source.index('WHEN 3 =>', start)
            return re.sub(r'\s', '', source[start:end])
        self.assertEqual(cpu_slot(old), cpu_slot(new))
        self.assertIn('G_CAPTURE = (VCM[] == 2);', new)
        self.assertIn('G_SAMPLE = (VCM[] == 4);', new)
        for i in range(4):
            self.assertIn(f'MODE{i}[] = VDM{3-i}[];', new)
        # CT5 is physical CT[5], a derived clock; preserve the original IRQ
        # condition/clock as well as the shared raster feeding it.
        irq = "INTT = DFF(!(INTTX & (CTV[2..0] == 7)),CT5,,);"
        self.assertIn(irq.replace(" ", ""), re.sub(r"\s", "", old))
        self.assertIn(irq.replace(" ", ""), re.sub(r"\s", "", new))
        # Module interface, including pin-facing outputs, is byte-identical.
        self.assertEqual(old[old.index('SUBDESIGN'):old.index('VARIABLE')],
                         new[new.index('SUBDESIGN'):new.index('VARIABLE')])


class PackerTests(unittest.TestCase):
    def test_existing_c_packer_roundtrip_and_boundary_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            exe = tmp / 'packer'
            subprocess.run(['cc', str(ROOT / 'bin/Altera0pak.c'), '-o', str(exe)], check=True)
            rng = random.Random(50)
            vectors = [b'', bytes(range(256)), bytes([0])*254, bytes([0])*255,
                       bytes([0])*256, bytes([0])*65536,
                       bytes.fromhex('ffff627b3c00') + bytes(rng.randrange(256) for _ in range(80000))]
            for data in vectors:
                raw, packed, back = [tmp / n for n in ('raw', 'packed', 'back')]
                raw.write_bytes(data)
                subprocess.run([str(exe), str(raw), str(packed)], check=True, stdout=subprocess.DEVNULL)
                subprocess.run([str(exe), '-d', str(packed), str(back)], check=True, stdout=subprocess.DEVNULL)
                self.assertEqual(data, back.read_bytes())
                encoded = packed.read_bytes(); output = bytearray(); i = 0
                while i < len(encoded):
                    if encoded[i]: output.append(encoded[i]); i += 1
                    else:
                        self.assertGreater(encoded[i+1], 0)
                        output.extend(bytes(encoded[i+1])); i += 2
                self.assertEqual(data, output)


if __name__ == '__main__':
    unittest.main()
