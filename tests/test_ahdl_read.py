"""Source-linked read pipeline checks; not a fitter or gate-level simulation."""
import unittest
from pathlib import Path
from tools.ahdl_read_sim import ReadProgram
from tools.game_video_model import SRAM, Video, VCM

SOURCE = Path(__file__).resolve().parents[1] / 'altera/acex/GAME_K50/VIDEO2.TDF'


class Bench:
    def __init__(self, ram, source=None):
        self.program = ReadProgram(source or SOURCE.read_text())
        self.video = Video(ram)
        self.scroll_loads = 0

    def step(self):
        p, v = self.program, self.video
        # Actual TDF VLA determines the four asynchronous SRAM outputs. CPU
        # write circuitry/counters are checked separately against standard K50.
        banks = [bank[p.state['VLA'] >> 2] for bank in v.ram.banks]
        phase = v.phase
        p.set_inputs(CLK42=1, CT=(v.x % 8)*8 + phase, CTH=v.x//8, CTV=v.y,
                     VCM=VCM[phase], DIR_PORT=(v.page<<3)|(int(v.screen_off)<<4)|(v.border<<5),
                     BRD=v.border, VXA=v.cpu_address, MXWE=1,
                     **dict(zip(('VDM0','VDM1','VDM2','VDM3'), banks)))
        if p.get('G_SCROLL.ena'): self.scroll_loads += 1
        p.edge()
        sample = v.step()
        actual = p.state['VLA']
        expected = v.slots[-1][2]
        if actual != expected:
            raise AssertionError(f'VLA CT={phase}: {actual:#x} != {expected:#x}')
        if p.get('VAO') != expected >> 2: raise AssertionError('SRAM word address')
        if tuple(p.state['MODE'+str(i)] for i in range(4)) != v.mode:
            raise AssertionError('Descriptor bank/capture mismatch')
        if p.state['G_SCROLL'] != v.scroll: raise AssertionError('Scroll phase/value mismatch')
        if self.scroll_loads != v.scroll_loads: raise AssertionError('Repeated control update')
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
                     ('G_SCROLL[].ena = (VCM[] == 0) & G_CONTROL;',
                      'G_SCROLL[].ena = (VCM[] == 2) & G_CONTROL;'),
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


if __name__ == '__main__': unittest.main()
