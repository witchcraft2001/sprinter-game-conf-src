"""Directed checks of SCROLL AHDL expressions used by both game targets."""
import itertools
import re
import unittest
from pathlib import Path

from tools.ahdl_read_sim import Parser, ReadProgram

ACEX = Path(__file__).resolve().parents[1] / 'altera/acex'


def code(name):
    source = (ACEX / name).read_text()
    return re.sub(r'--[^\n]*', '', re.sub(r'%.*?%', '', source, flags=re.S))


class ScrollTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.video = code('GAME_K50/VIDEO2.TDF')
        decl = cls.video.split('BEGIN', 1)[0]
        cls.widths = {name: int(high) + 1 if high else 1 for name, high in
                      re.findall(r'\b(\w+)(?:\[(\d+)\.\.0\])?\s*:\s*(?:INPUT|OUTPUT|NODE|DFFE?|LCELL)\s*;', decl)}

    def equation(self, lhs, clock=None, scope=None):
        pattern = r'^\s*' + re.escape(lhs) + r'\s*=\s*([^;]+);'
        expr, = re.findall(pattern, self.video if scope is None else scope, re.M)
        if clock:
            expr, = re.fullmatch(r'DFF\((.*),\s*' + clock + r',,\)', expr).groups()
        parser = Parser(expr, self.widths)
        tree = parser.expr()
        self.assertEqual(parser.peek(), '')
        return lambda **signals: self.value(tree, signals)

    def value(self, tree, signals):
        # ReadProgram.evaluate interprets the parsed tree with these input pins.
        self.signals = signals
        return self.evaluate(tree)[0]

    def get(self, name):
        return self.signals[name]

    evaluate = ReadProgram.evaluate

    def test_descriptor_fetch_and_offset_latch(self):
        slot = self.video.split('CASE VCM[1..0] IS')[1].split('WHEN 3 =>')[1].split('END CASE;')[0]
        address = self.equation('VLA_NEXT[]', scope=slot)
        wr_mode = self.equation('WR_MODE.d', scope=slot)
        shift_clock = self.equation('SHIFT_CLK0.d')
        source = ''.join(self.video.split())
        for n in range(4):
            self.assertIn(f'MODE{n}[].d=VDM{3-n}[];', source)
            self.assertIn(f'MODE{n}[].clk=LWR_MODE;', source)
        for lhs, rhs in [
                ('LWR_MODE', 'LCELL(LCELL(WR_MODE))'),
                ('GRID_X[2..0].ena', 'PIX_ENA'),
                ('GRID_X[8..3].ena', 'VCC'),
                ('SHIFT_CLK.d', 'SHIFT_CLK0'),
                ('(SHIFT_CLK0.clk,SHIFT_CLK.clk)', 'CLK42'),
                ('(SHIFT_X[].clk,SHIFT_Y[].clk)', 'SHIFT_CLK'),
                ('(SHIFT_X[].ena,SHIFT_Y[].ena)', 'MODE02'),
                ('(SHIFT_Y[],SHIFT_X[])', 'MODE3[]')]:
            self.assertIn(f'{lhs}={rhs};', source)
        for page, x, y in itertools.product(range(2), (0, 3, 4, 7, 8, 511), (0, 7, 8, 511)):
            self.assertEqual(address(DIR_PORT=page << 3, GRID_X=x, GRID_Y=y),
                             (page << 17) | ((x >> 2) << 10) | 0x300 | ((y >> 3) << 2))
        for x, half_cell in itertools.product(range(8), (False, True)):
            self.assertEqual(wr_mode(GRID_X=x, MODE0=0 if half_cell else 0x20),
                             x != 7 and not (half_cell and x == 3))
        for vcm, pixel in itertools.product(range(6), range(8)):
            self.assertEqual(shift_clock(VCM=vcm, CT=pixel << 3), (vcm, pixel) != (3, 7))

    def test_shift_commits_on_delayed_boundary_when_enabled(self):
        # Advance the two clock registers together, then clock the fine offsets
        # on the resulting rising edge. Change MODE3 inside each physical cell.
        first_d = self.equation('SHIFT_CLK0.d')
        second_d = self.equation('SHIFT_CLK.d')
        enabled = self.equation('(SHIFT_X[].ena,SHIFT_Y[].ena)')
        data = self.equation('(SHIFT_Y[],SHIFT_X[])')
        first, second, offset = 1, 1, 0
        changes = []
        # VCM is registered. At CT=0 its input was decoded at CT=6.
        decode = {int(bits, 2): int(v) for bits, v in
                  re.findall(r'WHEN B"([01]{3})" => VCM\[2\.\.0\]\.d = (\d);', self.video)}
        vcm_slots = [decode[ct] for ct in (6, 0, 1, 2, 4, 5)]
        for cell, command in enumerate((0xa3, None, 0x5c, 0)):
            for x, vcm in itertools.product(range(8), vcm_slots):
                mode3 = (command or 0) if x >= 3 else 0xee
                mode0 = 0 if command is None else 4
                new_first = first_d(VCM=vcm, CT=x << 3)
                new_second = second_d(SHIFT_CLK0=first)
                if new_second and not second and enabled(MODE0=mode0):
                    offset = data(MODE3=mode3)
                    changes.append((cell, x, vcm, offset & 15, offset >> 4))
                first, second = new_first, new_second
            self.assertEqual(offset, (0xa3, 0xa3, 0x5c, 0)[cell])
        self.assertEqual(changes, [(0, 7, 0, 3, 10), (2, 7, 0, 12, 5), (3, 7, 0, 0, 0)])

    def test_grid_and_pixel_address_at_wrap(self):
        grid_x, grid_y = self.equation('GRID_X[]'), self.equation('GRID_Y[]')
        src_x, src_y, addr = (self.equation(name) for name in ('SOURCE_X[]', 'SOURCE_Y[]', 'SVA[]'))
        for offset in range(16):
            for pos in (0, 3, 7, 8, 447, 511):
                self.assertEqual(grid_x(CTH=pos >> 3, CT=(pos & 7) << 3, SHIFT_X=offset) & 511,
                                 (pos + offset) % 512)
                self.assertEqual(grid_y(CTV=pos, SHIFT_Y=offset) & 511, (pos + offset) % 512)
        for x, y, dx, dy in itertools.product((0, 3, 254, 255, 511, 1023), (0, 255), range(8), range(8)):
            sx = src_x(MODE0=x >> 8, MODE1=x & 255, GRID_X=dx) & 1023
            sy = src_y(MODE2=y, GRID_Y=dy) & 255
            self.assertEqual(addr(SOURCE_X=sx, SOURCE_Y=sy),
                             ((y + dy) % 256) * 1024 + (((x + dx) % 1024) ^ 3))

    def test_irq_on_sampled_falling_marker_and_blank(self):
        bord = self.equation('BORD', 'LWR_COL')
        blank = self.equation('BLANK', 'LWR_COL')
        mark = self.equation('INTTX', 'LWR_COL')
        delay = self.equation('INTTX_N_DELAY.d')
        self.assertEqual(self.equation('INTTX_N_DELAY.clk')(CT=32), 1)
        self.assertEqual(self.equation('INTTX_N_DELAY.clk')(CT=31), 0)
        irq = self.equation('INTT', 'CT5')
        for mode, screen_off in itertools.product(range(256), (False, True)):
            border = bord(MODE0=mode)
            self.assertEqual(border, mode >= 0xf0)
            self.assertEqual(blank(BORD=border, MODE0=mode, DIR_PORT=screen_off << 4), screen_off or mode >= 0xfc)
            self.assertEqual(mark(BORD=border, MODE0=mode), mode in (0xfd, 0xff))
        delayed, pulses = 1, []
        for marker in (0, 1, 1, 0, 0, 1, 0, 0):
            pulses.append(irq(INTTX_N_DELAY=delayed, INTTX=marker))
            delayed = delay(INTTX=marker)
        self.assertEqual(pulses, [1, 1, 1, 0, 1, 1, 0, 1])

    def test_raster_counters_clocking_ay_match_standard(self):
        def counters(video):
            return ''.join(video.split('CT[5].clrn', 1)[1].split('CTF[]', 1)[0].split())

        old = counters(code('K50/VIDEO2.TDF'))
        new = counters(self.video)
        # SCROLL names the existing one-clock pixel enable register.
        explicit = 'PIX_ENA.clk=CLK42;PIX_ENA.d=CT0&CT2;CT[5..3].ena=PIX_ENA;'
        implicit = 'CT[5..3].ena=DFF((CT0&CT2),CLK42,,);'
        self.assertIn(explicit, new)
        self.assertEqual(new.replace(explicit, implicit), old)

    def test_game_irq_sources_and_audio_connections(self):
        top = ''.join(code('K50/SP2_ACEX.TDF').upper().split())
        for path in (
                'IF SCROLL_GAME == 1 GENERATE KEYS.INT_ENA = ALL_MODE0; ELSE GENERATE KEYS.INT_ENA = LCELL(ALL_MODE0 & ALL_MODE3);',
                'IF SCROLL_GAME == 1 GENERATE SVIDEO.ZX_PORT[7..6] = (DECODE.SP_SA,LCELL(DECODE.SP_SCR & !(A13 & !ACC.G_LINE7) & !ACC.G_LINE6 & ALL_MODE3)); SVIDEO.DIR_PORT[4] = RGMOD2;',
                'KEY/KEMS[] = (LCELL((KEYS.KBO5 & !CBL_MODE) OR (CBL_IND & CBL_MODE)),TAPE_IN,LCELL(CBL_MODE & CTV8),KEYS.KBO[4..0]);',
                'CBL_INT_ENA = CBL_XX4;',
                'CBL_INT = DFF(GND,!CBL_CNT6,,(CBL_INT_ENA & (/IO OR /M1)));',
                'INT_X = !DFF(GND,(SVIDEO.INTT & KEYS.INT),,((/IO OR /M1) & DFF(DFF(!INT_X,CTH2,,),CTH2,,))) OR !CBL_INT;',
                'MA[14..12] = (!TURBO,INT_X,NMI_X);',
                'AY/PORTS[] = AY3.DO[];',
                'AY3.AY_T[8..0] = (CTH[2..0],CT[5..0]);',
                'WHEN 0 => AY_FULL[] = (AY3.AY_CH_L[],GND);',
                'WHEN 1 => AY_FULL[] = (AY3.AY_CH_R[],GND);',
                'AY_CHS[].D = (((GND,AY_FULL[]) + (VCC,CBL_R[15..5])),CBL_R[4..1]);',
                'AUDIO_R[15..0].D = AY_CHS[15..0];',
                'DAC_DATA = DFFE(DFF(AUDIO_R15,CT2,,),!CT2,,,);'):
            self.assertIn(''.join(path.split()), top)
