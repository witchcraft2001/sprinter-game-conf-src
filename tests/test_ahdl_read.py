"""Source-linked read pipeline checks; not a fitter or gate-level simulation."""
import unittest
import re
from pathlib import Path
from tools.ahdl_read_sim import ReadProgram, Parser
from tools.game_video_model import SRAM, Video, VCM, PERIOD_NS, palette_address

SOURCE = Path(__file__).resolve().parents[1] / 'altera/acex/GAME_K50/VIDEO2.TDF'


class Bench:
    def __init__(self, ram, source=None):
        self.program = ReadProgram(source or SOURCE.read_text())
        self.video = Video(ram)
        self.scroll_loads = 0
        self.bus = SRAM(ram.latency_ns, ram.address_delay_ns, ram.fpga_input_delay_ns,
                        ram.dac_setup_ns)
        self.bus.banks = ram.banks
        self.rgb_clocks = 0
        self.rgb = None

    def step(self):
        p, v = self.program, self.video
        # Actual TDF VLA determines the four asynchronous SRAM outputs. CPU
        # write circuitry/counters are checked separately against standard K50.
        banks = [bank[self.bus.address] for bank in self.bus.banks]
        phase = v.phase
        p.set_inputs(CLK42=1, CT=(v.x % 8)*8 + phase, CTH=v.x//8, CTV=v.y,
                     VCM=VCM[phase], DIR_PORT=(v.page<<3)|(int(v.screen_off)<<4)|(v.border<<5),
                     BRD=v.border, VXA=v.cpu_address, MXWE=1,
                     **dict(zip(('VDM0','VDM1','VDM2','VDM3'), banks)))
        if p.get('G_SCROLL.ena'): self.scroll_loads += 1
        # Setup checks follow enables/strobe from the actual TDF, not the
        # reference model's phase schedule. Too-early capture must fail even
        # when zero-delay bank values happen to be logically correct.
        if p.get('G_CAPTURE') or p.get('G_SAMPLE'):
            self.bus.read_banks(v.now)
        strobe_before = p.state['TSN_W3']
        p.edge()
        if not strobe_before and p.state['TSN_W3']:
            self.rgb = self.bus.read_banks(v.now, receiver='dac')[1:]
            self.rgb_clocks += 1
            if phase != 0: raise AssertionError('RGB clock outside palette slot')
            if v.sample is not None and self.bus.address != palette_address(v.palette) >> 2:
                raise AssertionError('RGB clock on non-palette SRAM address')
        self.bus.issue(p.state['VLA'], v.now)
        sample = v.step()
        if (self.rgb_clocks, self.rgb) != (v.rgb_clocks, v.rgb):
            raise AssertionError('External RGB clock/data mismatch')
        actual = p.state['VLA']
        expected = v.slots[-1][2]
        if actual != expected:
            raise AssertionError(f'VLA CT={phase}: {actual:#x} != {expected:#x}')
        if p.get('VAO') != expected >> 2: raise AssertionError('SRAM word address')
        if tuple(p.state['MODE'+str(i)] for i in range(4)) != v.mode:
            raise AssertionError('Descriptor bank/capture mismatch')
        if p.state['G_SCROLL'] != v.scroll: raise AssertionError('Scroll phase/value mismatch')
        if self.scroll_loads != v.scroll_loads: raise AssertionError('Repeated control update')
        if bool(p.state['G_PENDING_VALID']) != (v.pending is not None):
            raise AssertionError('Pending control lifetime')
        if v.pending is not None and p.state['G_PENDING'] != v.pending:
            raise AssertionError('Pending MODE3 value')
        if sample:
            actual = tuple(p.state[n] for n in ('G_COLOR','G_BLANK','G_IRQ')) + (p.get('G_PALETTE'),)
            expected = (sample.color, int(sample.blank), int(sample.irq), sample.palette)
            if actual != expected: raise AssertionError(f'Pixel metadata {actual} != {expected}')
        return sample

    def pixels(self, count):
        seen = []
        while len(seen) < count:
            s = self.step()
            if s: seen.append(s)
        return seen


def fixture():
    from tests.test_game_video import GameVideoTests
    return GameVideoTests().fixture()


class AhdlReadTests(unittest.TestCase):
    def test_descriptor_layout_and_preserved_game_origin(self):
        # The stock expressions independently specify descriptor layout, NOT
        # the final RGB position (that also needs the complete stock pipeline).
        # Preserve the pre-review game origin confirmed on the user's board.
        stock = (SOURCE.parent.parent / 'K50/VIDEO2.TDF').read_text()
        stock = re.sub(r'--[^\n]*', '', re.sub(r'%.*?%', '', stock, flags=re.S))
        slot = stock[stock.index('CASE VCM[1..0] IS'):]
        slot = slot[slot.index('WHEN 3 =>'):slot.index('END CASE;')]
        addr = re.search(r'VLA\[\]\.d\s*=\s*([^;]+)', slot)[1]
        strobe = re.search(r'WR_MODE\.d\s*=\s*([^;]+)', slot)[1]
        ram = fixture()
        for row_y in (0, 7, 8, 255, 319):
            for col in (0, 1, 38, 39, 55):
                bench = Bench(ram)
                p = bench.program
                p.state['MODE0'] = 0x20  # stock 320-pixel byte graphics
                p.set_inputs(CT=7*8+4, CTH=col, CTV=row_y, DIR_PORT=0)
                expected = p.evaluate(Parser(addr, p.widths).expr())[0]
                self.assertEqual(p.evaluate(Parser(strobe, p.widths).expr())[0], 0)
                p.state['MODE0'] = 0
                bench.video.x, bench.video.y = (col*8-1) % 448, row_y
                bench.pixels(1)  # prefetch for the next physical cell
                cell = bench.pixels(8)
                self.assertTrue(all(s.descriptor == expected for s in cell))
                self.assertEqual([s.y for s in cell], [row_y]*8)

    def test_control_preserves_whole_cell_then_bypasses_next_scroll(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for value in range(256):
            ram.load(descriptor_address(0, 16, 5), (0x24, 19, 90, value))
            bench = Bench(ram)
            bench.video.scroll = bench.program.state['G_SCROLL'] = 0x57
            bench.video.x = 8  # old X scroll=7; next request is grid X=16
            bench.pixels(1)
            for x in range(8):
                sample = bench.pixels(1)[0]
                self.assertEqual((sample.x, sample.y), (16+x, 5))
                self.assertEqual(sample.address, 95*1024+19+x)
                self.assertEqual(bench.video.scroll, value if x == 7 else 0x57)
                if x == 0:
                    # A CPU update while still inside the cell must not
                    # replace the MODE3 latched on entry.
                    ram.write(descriptor_address(0, 16, 5)+3, value ^ 255)
            self.assertEqual(bench.scroll_loads, 1)
            sample = bench.pixels(1)[0]
            self.assertEqual((sample.x, sample.y), (17+(value & 15), value >> 4))

    def test_entire_raster_both_pages(self):
        bench = Bench(fixture())
        bench.pixels(1)
        for page in (0, 1):
            bench.video.page = page
            bench.pixels(1)
            seen = {(s.x,s.y) for s in bench.pixels(448*320)}
            self.assertEqual(len(seen), 448*320)

    def test_all_scroll_values_at_cell_line_and_frame_boundaries(self):
        ram = fixture()
        for sy in range(16):
            for sx in range(16):
                bench = Bench(ram)
                bench.video.scroll = bench.program.state['G_SCROLL'] = sx | (sy<<4)
                bench.video.x, bench.video.y = 383, 319
                bench.pixels(75)  # CTV edge at 391, horizontal edge at 447

    def test_special_descriptors_controls_page_switch_and_screen_off(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for page in (0, 1):
            for col,m0 in enumerate((0x24,0x64,0xa4,0xc0,0xe4,0xf4,0xfc,0xfd,0xfe,0xff)):
                ram.load(descriptor_address(page,col*8,0), (m0,255,255,0))
            ram.load(descriptor_address(page,424,312), (0xf4,0,0,0xff))
        bench = Bench(ram)
        bench.video.border = 7
        bench.pixels(90)
        bench.video.page = 1
        bench.pixels(448)
        bench.video.screen_off = True
        bench.pixels(448)
        bench.video.screen_off = False
        bench.video.x, bench.video.y = 423, 312
        bench.pixels(448*2)
        self.assertEqual(bench.video.scroll, 255)

    def test_unaligned_address_wrap_and_all_banks(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for base in (0,1,2,3,255,256,1019,1023):
            ram.load(descriptor_address(0,8,0), (0x20|(base>>8),base&255,255,0))
            bench = Bench(ram); bench.video.x = 7
            bench.pixels(9)

    def test_mutations_in_source_are_detected(self):
        source = SOURCE.read_text()
        mutations = [('MODE3[] = VDM0[];', 'MODE3[] = VDM1[];'),
                     ('WHEN 1 => G_INDEX[] = VDM2[];', 'WHEN 1 => G_INDEX[] = VDM0[];'),
                     ('G_SCROLL[].ena = (VCM[] == 4) & G_APPLY;',
                      'G_SCROLL[].ena = (VCM[] == 0) & G_APPLY;'),
                     ('TSN_W3.d = (VCM[] != 0);', 'TSN_W3.d = (VCM[1..0] != 0);'),
                     ('G_SUM_X[] >= 448', 'G_SUM_X[] >= 447')]
        from tools.game_video_model import descriptor_address
        for old,new in mutations:
            with self.subTest(mutation=old):
                self.assertIn(old, source)
                ram = fixture()
                ram.load(descriptor_address(0,424,312), (0x24,1,90,0x0f))
                bench = Bench(ram, source.replace(old,new))
                bench.video.x, bench.video.y = 423,312
                with self.assertRaises(AssertionError): bench.pixels(40)

    def test_two_period_reads_with_separate_fpga_and_dac_budgets(self):
        ram = fixture()
        # 6 + 15 + 9 = 30 ns for the FPGA round trip, > one 23.81 ns
        # period; 6 + 15 + 2 = 23 ns for the external RGB latch. Illustrative
        # budgets, not a timing specification for the user's fitted board.
        ram.address_delay_ns, ram.fpga_input_delay_ns, ram.dac_setup_ns = 6, 9, 2
        bench = Bench(ram)
        bench.pixels(900)
        source = SOURCE.read_text()
        # Old color capture at CT=1 must fail on the ACTUAL source bench.
        early = source.replace('G_SAMPLE = (VCM[] == 4);', 'G_SAMPLE = (VCM[] == 1);')
        with self.assertRaisesRegex(RuntimeError, 'setup'):
            Bench(ram, early).pixels(3)
        # Likewise reject moving the descriptor capture one edge earlier.
        early = source.replace('G_CAPTURE = (VCM[] == 2);', 'G_CAPTURE = (VCM[] == 3);')
        with self.assertRaisesRegex(RuntimeError, 'setup'):
            Bench(ram, early).pixels(3)

    def test_descriptor_hold_ignores_mid_request_page_change(self):
        bench = Bench(fixture())
        while bench.video.phase != 4: bench.step()  # CT=2 already issued page 0
        request = bench.program.state['VLA']
        bench.video.page = 1
        bench.step()  # CT=4 must hold the saved address for a second period
        self.assertEqual(bench.program.state['VLA'], request)
        bench.step()  # CT=5 captures page 0, not a mixture of two requests
        self.assertEqual(bench.program.state['G_LAST'], request >> 2)
        bench.pixels(3)
        self.assertEqual(bench.program.state['G_REQUEST'] >> 15, 1)

    def test_palette_strobe_cadence_and_rgb_data(self):
        ram = fixture()
        bench = Bench(ram)
        bench.pixels(1)  # discard startup data
        for _ in range(80):
            sample = bench.pixels(1)[0]
            word = palette_address(sample.palette) >> 2
            expected = tuple(ram.banks[b][word] for b in (1, 2, 3))
            old_count = bench.rgb_clocks
            while bench.video.phase != 0: bench.step()
            self.assertEqual(bench.rgb_clocks, old_count)
            bench.step()
            self.assertEqual(bench.rgb_clocks, old_count + 1)
            self.assertEqual(bench.rgb, expected)

    def test_dac_setup_remains_a_separate_one_period_constraint(self):
        ram = fixture()
        ram.dac_setup_ns = PERIOD_NS  # total exceeds palette's one period
        with self.assertRaisesRegex(RuntimeError, 'setup'):
            Bench(ram).pixels(3)


if __name__ == '__main__': unittest.main()
