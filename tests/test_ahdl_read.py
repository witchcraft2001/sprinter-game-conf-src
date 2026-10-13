"""Source-linked read pipeline checks; not a fitter or gate-level simulation."""
import unittest
import re
import os
from pathlib import Path
from tools.ahdl_read_sim import ReadProgram, Parser
from tools.game_video_model import SRAM, Video, VCM, PERIOD_NS, palette_address

ROOT = Path(__file__).resolve().parents[1]
# Allow the same checks to execute the exact staged K30/K50 source, including
# the target-specific scroll-register transform performed by the build script.
SOURCE = Path(os.environ.get('GAME_VIDEO_TDF', ROOT / 'altera/acex/GAME_K50/VIDEO2.TDF'))
STOCK_SOURCE = ROOT / 'altera/acex/K50/VIDEO2.TDF'


class Bench:
    def __init__(self, ram, source=None):
        source = source or SOURCE.read_text()
        self.program = ReadProgram(source)
        self.video = Video(ram, hold_border_data='MODE1[].ena = G_MODE_CAPTURE;' in source)
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

    def initial_scroll(self, value):
        self.video.scroll = self.program.state['G_SCROLL'] = value
        # Nonzero initial offsets are testbench injection, not power-up.
        # Seed the retained prefetch copy consistently with that injected Q.
        if 'G_EFFECTIVE' in self.program.state:
            self.program.state['G_EFFECTIVE'] = value
        if 'G_EFFECTIVE_X' in self.program.state:
            self.program.state['G_EFFECTIVE_X'] = value & 15


def fixture():
    from tests.test_game_video import GameVideoTests
    return GameVideoTests().fixture()


class AhdlReadTests(unittest.TestCase):
    def test_scroll_reads_descriptors_beyond_physical_raster(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for page in (0, 1):
            # Different sentinels at the requested and formerly wrapped cells.
            extended = descriptor_address(page, 448, 320)
            alias = descriptor_address(page, 0, 0)
            ram.load(extended, (0x20, 101, 80, 0))
            ram.load(alias, (0x20, 201, 90, 0))
            ram.write(80*1024+101, 0xa5)
            ram.write(90*1024+201, 0x5a)
            bench = Bench(ram)
            bench.initial_scroll(0x11)
            bench.video.page = page
            bench.video.x, bench.video.y = 6, 319
            sample = bench.pixels(2)[1]
            self.assertEqual((sample.x, sample.y), (448, 320))
            self.assertEqual(sample.descriptor, extended)
            self.assertEqual(sample.address, 80*1024+101)
            self.assertEqual(sample.color, 0xa5)
    def test_titd_camera_last_column_is_clipped_at_fixed_screen_edge(self):
        from tools.game_video_model import descriptor_address
        # lowram_object_step_d: seed 24/0/0/0F replaces column 39 when
        # fine=0 and is ORed with its graphics otherwise; E4 is column 40.
        # Hidden column 55 loads fine scroll. The visible viewport ends at
        # physical byte X=319; column 39 supplies only its fine-scroll tail.
        for page in (0, 1):
            for camera in range(24):
                coarse, fine = divmod(camera, 8)
                ram = SRAM()
                ram.load(64*1024, bytes(1 + (x % 251) for x in range(512)))
                for col in range(56):
                    for row in range(40):
                        base = (col + coarse)*8
                        mode = (0x60 | (base >> 8), base & 255, 64, 0) if col < 39 else (0xe4, 0, 0, 0)
                        if col == 39:
                            mode = (0x64 | (base >> 8), base & 255, 64, 15) if fine else (0x24, 0, 0, 15)
                        if col == 55:
                            mode = (0xf4, 0, 0, fine)
                        ram.load(descriptor_address(page, col*8, row*8), mode)
                b = Bench(ram)
                b.video.page, b.video.x = page, 431
                seen = {}
                for _ in range(448):
                    sample = b.pixels(1)[0]
                    if 8 <= b.video.x < 336:
                        seen[b.video.x] = sample.palette
                self.assertEqual([seen[x] for x in range(8, 320)],
                                 [256 + 1 + ((x-8+camera) % 251) for x in range(8, 320)],
                                 (page, camera))
                self.assertEqual([x for x in range(304, 336) if 256 <= seen[x] < 512],
                                 list(range(304, 320)), (page, camera))

    def test_border_reload_preserves_flags_and_releases_next_graphics(self):
        from tools.game_video_model import descriptor_address
        for page in (0, 1):
            for control in (0xe4, 0xf4, 0xfc, 0xfd, 0xfe, 0xff):
                ram = SRAM()
                for col in range(56):
                    for row in (0, 1):
                        ram.load(descriptor_address(page, col*8, row*8), (0x60, 19, 90, 0))
                ram.load(descriptor_address(page, 320, 8), (control, 0, 0, 0))
                b = Bench(ram)
                b.initial_scroll(0x8f)
                b.video.page, b.video.x, b.video.border = page, 312, 5
                samples = b.pixels(17)[1:]
                # Eight original border pixels plus seven clipped pixels.
                # The Y reload then selects graphics in row 0: do not keep
                # the guard into that next cell, line or page.
                expected = 0x400 if control >= 0xfc else 0x42d
                self.assertEqual([s.palette for s in samples[:15]], [expected]*15)
                self.assertTrue(all(s.blank == (control >= 0xfc) for s in samples[:15]))
                self.assertTrue(all(s.irq == (control in (0xfd, 0xff)) for s in samples[:15]))
                self.assertLess(samples[15].palette, 0x400)
                self.assertFalse(samples[15].blank or samples[15].irq)
                self.assertEqual(b.video.scroll, 0)

    def test_right_border_does_not_replay_graphics_after_scroll_reload(self):
        from tools.game_video_model import descriptor_address
        # TITD lowram_object_step_d writes E4/0/0/0 to column 40;
        # its left control can load 0F. 15 -> 0 at the right control's
        # tail used to revisit column 39 for seven visible pixels.
        # Sweep reload values too: only a backwards crossing of the
        # preceding descriptor must be clipped, with no hardcoded width.
        for page in (0, 1):
            for old in range(16):
                for new in range(16):
                    ram = SRAM()
                    for col in range(56):
                        # Replayed graphics also carry a control: it must
                        # neither become visible nor change scroll again.
                        mode = (0x24, 19, 90, old) if col < 40 else (0xe4, 0, 0, new)
                        ram.load(descriptor_address(page, col*8, 0), mode)
                    b = Bench(ram)
                    b.initial_scroll(old)
                    b.video.page, b.video.border = page, 3
                    first_border = 328 - old
                    b.video.x = first_border - 2
                    samples = b.pixels(26)[1:]
                    self.assertLess(samples[0].palette, 0x400)
                    self.assertEqual([s.palette for s in samples[1:]], [0x41b]*24,
                                     (page, old, new))
                    self.assertEqual(b.video.scroll, new)

    def test_horizontal_origin_wrap_exhaustive(self):
        program = ReadProgram(SOURCE.read_text())
        # Full reachable sum range, including power-up zero. Independent
        # modulo arithmetic checks the source's partial-bit assignments.
        for total in range(464):
            program.state['G_SUM_X'] = total
            program.set_inputs(CLK42=1)
            self.assertEqual(program.driver('G_X'), (total - 8) & 511, total)

    def test_horizontal_origin_all_positions_and_scrolls(self):
        # Execute the actual coordinate registers, with arithmetic expectations
        # independent of Video. Include both sides of the origin and X wrap.
        p = ReadProgram(SOURCE.read_text())
        for scroll in range(16):
            for physical_x in range(448):
                p.state['G_SCROLL'] = scroll | (scroll << 4)
                if 'G_EFFECTIVE_X' in p.state:
                    p.state['G_EFFECTIVE_X'] = scroll
                else:
                    p.state['G_EFFECTIVE'] = scroll | (scroll << 4)
                p.set_inputs(CLK42=1, CT=(physical_x % 8)*8, CTH=physical_x//8,
                             CTV=319, VCM=5, DIR_PORT=0, BRD=0, VXA=0,
                             MXWE=1, VDM0=0, VDM1=0, VDM2=0, VDM3=0)
                p.edge()  # CT=0: sum the physical advance and scroll
                p.set_inputs(CT=(physical_x % 8)*8+1, VCM=1)
                p.edge()  # CT=1: horizontal origin bias + raster wrap
                expected_x = (physical_x + 1 + scroll + (440 if physical_x < 7 else -8)) & 511
                expected_y = (scroll if physical_x == 391 else 319 + scroll) & 511
                self.assertEqual(p.state['G_X'], expected_x)
                self.assertEqual(p.state['G_Y'], expected_y)

    def test_pixel_pipeline_independent_xy_wrap(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for base in (0, 1, 2, 3, 254, 255, 256, 1019, 1023):
            for row in (0, 249, 255):
                for local_y in (0, 1, 7):
                    ram.load(descriptor_address(0, 8, 0), (0x20 | (base >> 8), base & 255, row, 0))
                    bench = Bench(ram)
                    bench.video.x, bench.video.y = 15, local_y
                    samples = bench.pixels(9)[1:]
                    self.assertEqual([s.address for s in samples],
                                     [(((row + local_y) & 255) << 10) | ((base + x) & 1023)
                                      for x in range(8)])

    def test_border_updates_and_cpu_addresses_at_every_phase(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for page in (0, 1):
            for col in range(56):
                ram.load(descriptor_address(page, col * 8, 0), (0xe0, 255, 255, 0))
        bench = Bench(ram)
        # A CPU border write must not change a color already sampled for
        # the palette slot. Exercise each phase, the bus mux and byte bits.
        for cycle in range(600):
            bench.video.border = (cycle * 3) & 7
            bench.video.cpu_address = (cycle * 7919) & 0x3ffff
            bench.step()

    def test_write_capture_truth_table_preserved(self):
        source = SOURCE.read_text()
        stock = STOCK_SOURCE.read_text()
        old = re.search(r'^\s*E_WR\s*=\s*LCELL\((.*)\);', stock, re.M)[1]
        capture = re.search(r'^\s*G_WRITE_CAPTURE\s*=\s*([^;]+);', source, re.M)[1]
        p = ReadProgram(source)
        p.widths.update(WR=1, WR_PREV=1, VAI=20, ZX_SCREEN=1)
        old = Parser(old.replace('DFF(WR,CLK42,,)', 'WR_PREV'), p.widths).expr()
        capture = Parser(capture.replace('DFF(WR,CLK42,,)', 'WR_PREV'), p.widths).expr()
        for wr in (0, 1):
            for previous in (0, 1):
                for graphics in (0, 1):
                    for zx in (0, 1):
                        p.set_inputs(WR=wr, WR_PREV=previous, VAI=graphics << 19, ZX_SCREEN=zx)
                        self.assertEqual(p.evaluate(capture)[0], 1 - p.evaluate(old)[0])
        self.assertIn('E_WR = !G_WRITE_CAPTURE;', source)
        self.assertIn('VXA[].ena  = G_WRITE_CAPTURE;', source)
        self.assertIn('DOUBLE.ena = G_WRITE_CAPTURE;', source)

    def test_descriptor_layout_and_one_cell_display_origin(self):
        # The stock expressions independently specify descriptor layout, NOT
        # the final RGB position (that also needs the complete stock pipeline).
        # After the HOLD fix, the board shows a remaining one-cell left shift.
        # Descriptor c must therefore be fetched in physical cell c+1.
        stock = STOCK_SOURCE.read_text()
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
                bench.video.x, bench.video.y = (col*8+7) % 448, row_y
                bench.pixels(1)  # prefetch for the next physical cell
                cell = bench.pixels(8)
                self.assertTrue(all(s.descriptor == expected for s in cell))
                self.assertEqual([s.y for s in cell], [row_y]*8)

    def test_graphics_control_closes_at_physical_boundary_then_bypasses_scroll(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for value in range(256):
            ram.load(descriptor_address(0, 16, 5), (0x24, 19, 90, value))
            bench = Bench(ram)
            bench.initial_scroll(0x57)
            bench.video.x = 16  # origin -8 + old scroll 7; next grid X=16
            bench.pixels(1)
            # Source cell begins at physical X=17. Its last visible byte
            # before physical X=24 has local X=6, so reload must not wait
            # for local X=7. This is the partial-cell case used by TITD.
            for x in range(7):
                sample = bench.pixels(1)[0]
                self.assertEqual((sample.x, sample.y), (16+x, 5))
                self.assertEqual(sample.address, 95*1024+19+x)
                self.assertEqual(bench.video.scroll, value if x == 6 else 0x57)
                if x == 0:
                    # A CPU update while still inside the cell must not
                    # replace the MODE3 latched on entry.
                    ram.write(descriptor_address(0, 16, 5)+3, value ^ 255)
            self.assertEqual(bench.scroll_loads, 1)
            sample = bench.pixels(1)[0]
            self.assertEqual((sample.x, sample.y), (16+(value & 15), value >> 4))

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
                bench.initial_scroll(sx | (sy<<4))
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
        bench.video.x, bench.video.y = 431, 312
        bench.pixels(448*2)
        self.assertEqual(bench.video.scroll, 255)

    def test_unaligned_address_wrap_and_all_banks(self):
        from tools.game_video_model import descriptor_address
        ram = fixture()
        for base in (0,1,2,3,255,256,1019,1023):
            ram.load(descriptor_address(0,8,0), (0x20|(base>>8),base&255,255,0))
            bench = Bench(ram); bench.video.x = 15
            bench.pixels(9)

    def test_mutations_in_source_are_detected(self):
        source = SOURCE.read_text()
        mutations = [('MODE3[] = VDM0[];', 'MODE3[] = VDM1[];'),
                     ('WHEN 1 => G_INDEX[] = VDM2[];', 'WHEN 1 => G_INDEX[] = VDM0[];'),
                     ('G_SCROLL[].ena = (VCM[] == 4) & G_APPLY;',
                      'G_SCROLL[].ena = (VCM[] == 0) & G_APPLY;'),
                     ('TSN_W3.d = (VCM[] != 0);', 'TSN_W3.d = (VCM[1..0] != 0);'),
                     ('G_SUM_X[8..3] - B"000001"', 'G_SUM_X[8..3] - B"000010"')]
        from tools.game_video_model import descriptor_address
        for old,new in mutations:
            with self.subTest(mutation=old):
                self.assertIn(old, source)
                ram = fixture()
                ram.load(descriptor_address(0,424,312), (0x24,1,90,0x0f))
                bench = Bench(ram, source.replace(old,new))
                bench.video.x, bench.video.y = 431,312
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

    def test_confirmed_hc374_and_15ns_sram_do_not_close_at_42mhz(self):
        # Nexperia 74HC374: minimum setup 12 ns at VCC=4.5 V, 25 C;
        # ISSI -15 SRAM: maximum access 15 ns. Even ideal FPGA/PCB delay
        # cannot fit their 27 ns sum into the palette's 23.81 ns period.
        # A passing functional test must never imply this board timing closes.
        ram = fixture()
        ram.latency_ns, ram.dac_setup_ns = 15, 12
        self.assertGreater(27, PERIOD_NS)
        with self.assertRaisesRegex(RuntimeError, 'setup'):
            Bench(ram).pixels(3)


if __name__ == '__main__': unittest.main()
