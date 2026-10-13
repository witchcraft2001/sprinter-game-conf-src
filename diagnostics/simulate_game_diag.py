#!/usr/bin/env python3
"""Execute the actual GAMEDIAG EXE on z80 with DSS/BIOS/window/VRAM stubs.

Install-free command when uv is available:
  uv run --with z80 python diagnostics/simulate_game_diag.py
This validates software only. It does not execute the FPGA or model analog DAC.
"""
import re
from pathlib import Path
import z80
from make_assets import tiles, palettes

HERE = Path(__file__).resolve().parent
SYMBOLS = {name: int(value, 16) for name, value in re.findall(
    r'^([\w.]+): EQU 0x([0-9A-Fa-f]+)', (HERE / 'build/game_diag.sym').read_text(), re.M)}
IMAGE = (HERE / 'build/GAMEDIAG.EXE').read_bytes()


class Run:
    def __init__(self, size=12345, short_read=False, bios_error=False, version=(0x146, 998), bad_header=False, zero_run=1,
                 screen_position=0x77, cmos_error=False, ports_error=False):
        self.m = z80.Z80Machine()
        self.m.set_memory_block(0x8100, IMAGE[512:])
        self.m.pc, self.m.sp = 0x8100, 0xbfff
        self.file = bytes((255,255,98,123,60 if not bad_header else 57,0,zero_run)) + bytes(max(0, size-7))
        self.file = self.file[:size]
        self.position = 0
        self.short_read, self.bios_error, self.version = short_read, bios_error, version
        self.windows = [0, 1, 2, 3]
        self.pages = {}
        self.allocated = []
        self.setup = False
        self.screen_position, self.cmos_error, self.ports_error = screen_position, cmos_error, ports_error
        # Raw CMOS addresses, as in BIOS FUNC_CMOS.ASM / SP2000.inc.
        # Keep seconds different from ScreenPosition to detect a D=0 mistake.
        self.cmos = bytearray(128)
        self.cmos[0], self.cmos[0x1f] = 0x59, screen_position
        self.hold = None
        self.y = self.display = 0
        self.vram = bytearray(262144)
        self.outputs = []
        self.message = ''
        self.key = 0xff
        self.m.set_output_callback(self.output)
        self.m.set_input_callback(self.input)
        for address in (8, 0x10, 0x18, SYMBOLS['poll']): self.m.set_breakpoint(address)

    def byte(self, name): return self.m.memory[SYMBOLS[name]]

    def pop(self):
        value = self.m.memory[self.m.sp] | (self.m.memory[(self.m.sp+1)&65535] << 8)
        self.m.sp = (self.m.sp + 2) & 65535
        return value

    def flush(self):
        if self.windows[3] == 0x50:
            self.vram[self.y*1024:(self.y+1)*1024] = self.m.memory[0xc000:0xc400]
        else:
            self.pages[self.windows[3]] = bytearray(self.m.memory[0xc000:0x10000])

    def output(self, port, value):
        port &= 255
        if port == 0xe2:
            self.flush()
            self.windows[3] = value
            if value == 0x50:
                self.m.set_memory_block(0xc000, bytes(self.vram[self.y*1024:(self.y+1)*1024]) + bytes(15360))
            else: self.m.set_memory_block(0xc000, bytes(self.pages.setdefault(value, bytearray(16384))))
        elif port == 0x89:
            self.flush(); self.y = value
            if self.windows[3] == 0x50:
                self.m.set_memory_block(0xc000, bytes(self.vram[self.y*1024:(self.y+1)*1024]))
        elif port == 0xc9: self.display = value
        self.outputs.append((port, value))

    def input(self, port):
        if port & 255 == 0xe2: return self.windows[3]
        if port == 0xf7fe:
            key = self.key; self.key = 0xff
            return key
        return 0xff

    def dss(self):
        self.m.f &= 0xfe
        if self.m.c == 0:
            self.m.de, self.m.bc = self.version
        elif self.m.c == 0x11:
            self.m.a = 5
        elif self.m.c == 0x15:
            if self.m.b == 2:
                self.m.hl, self.m.ix = len(self.file) >> 16, len(self.file) & 65535
            elif self.m.b == 0:
                self.position = (self.m.hl<<16)|self.m.ix
                self.m.hl,self.m.ix = self.position>>16,self.position&65535
            elif self.m.b == 1:
                self.position += (self.m.hl<<16)|self.m.ix
                self.m.hl,self.m.ix = self.position>>16,self.position&65535
            else: raise AssertionError('Invalid seek mode')
        elif self.m.c == 0x3d:
            self.allocated = list(range(0x70, 0x70 + self.m.b))
            self.m.a = self.allocated[0]
        elif self.m.c == 0x13:
            count = self.m.de
            data = self.file[self.position:self.position + count - int(self.short_read)]
            self.m.set_memory_block(self.m.hl, data)
            self.position += len(data)
            self.m.de = 0xdead  # not an API result; deliberately poison it
            self.m.a = 255 if self.position >= len(self.file) else 0
            # EOF includes an exact read ending at file size; carry remains clear.
        elif self.m.c == 0x12: pass
        elif self.m.c == 0x5c:
            pointer = self.m.hl
            while self.m.memory[pointer]:
                self.message += chr(self.m.memory[pointer]); pointer += 1
        elif self.m.c == 0x41: return 'exit'
        else: raise AssertionError('Unexpected DSS call %02x' % self.m.c)

    def bios(self):
        self.m.f &= 0xfe
        if self.m.c == 0xc5:
            # Exact BIOS semantics: page list followed by FF, B=count.
            self.m.set_memory_block(self.m.hl, bytes(self.allocated + [255]))
            self.m.b = len(self.allocated)
        elif self.m.c == 0xf3:
            assert self.m.a == 0xfe and self.m.b == self.allocated[0]
            self.flush()
            payload = b''.join(bytes(self.pages[p]) for p in self.allocated)
            assert payload[:len(self.file)] == self.file
            assert payload[len(self.file):] == bytes([255]) * (len(payload)-len(self.file))
            assert len(self.allocated) == (len(self.file)+16383)//16384
            self.setup = not self.bios_error
            if self.bios_error: self.m.f |= 1
        elif self.m.c == 0xf6:
            assert self.setup and self.m.d < len(self.cmos)
            self.m.a = self.cmos[self.m.d]
            if self.cmos_error: self.m.f |= 1
        elif self.m.c == 0xf8:
            assert self.setup and self.m.a == 0xcb and self.m.b == self.screen_position
            if self.ports_error: self.m.f |= 1
            else: self.hold = self.m.b
        else: raise AssertionError('Unexpected BIOS call %02x' % self.m.c)

    def run(self, press=None):
        if press is not None:
            self.key = 255 ^ (1 << (press-1))
            self.m.step_over_breakpoint()
        for _ in range(100):
            self.m.ticks_to_stop = 1_000_000
            self.m.run()
            pc = self.m.pc
            if pc == SYMBOLS['poll']:
                self.flush()
                return 'poll'
            if pc == 0x18: return 'reset'
            if pc in (8, 0x10):
                ret = self.pop()
                result = self.bios() if pc == 8 else self.dss()
                if result == 'exit': return 'exit'
                self.m.pc = ret
        raise AssertionError('Execution timeout at %04x' % self.m.pc)


def check_maps(run, scroll):
    for page in range(2):
        for col in range(58):
            for row in range(42):
                address = (page << 17) | (col << 11) | 0x700 | (row << 2)
                mode = run.vram[address:address+4]
                xbase = col*8 if page == 0 else (55-col)*8
                assert mode[2] == 128 and mode[3] == scroll
                if col < 40 and row < 32:
                    assert ((mode[0] & 3) << 8 | mode[1]) == xbase
                    assert mode[0] >> 6 == row % 4
                elif row >= 32 and col != 53:
                    assert mode[0] & 0xfc == 0xfc
                    assert bool(mode[0] & 1) == (row == 39)


def main():
    checks = 0
    for size in (7, 16383, 16384, 16385, 32768, 49153, 65536):
        run = Run(size=size)
        assert run.run() == 'poll' and run.setup
        assert run.byte('scroll') == 0, 'BIOS page-list terminator overwrote scroll'
        check_maps(run, 0)
        graphic = tiles()
        for y in range(8): assert run.vram[(128+y)*1024:(128+y)*1024+448] == graphic[y*448:(y+1)*448]
        pal = palettes()
        for y in range(256): assert run.vram[y*1024+0x3e0:y*1024+0x400] == pal[y*32:(y+1)*32]
        checks += 1
    run = Run(); assert run.run() == 'poll'
    for _ in range(16): assert run.run(1) == 'poll'
    assert run.byte('scroll') == 0
    for _ in range(16): assert run.run(2) == 'poll'
    assert run.byte('scroll') == 0
    assert run.run(1) == 'poll' and run.run(2) == 'poll'
    check_maps(run, 0x11)
    assert run.run(3) == 'poll' and run.display == 1
    assert run.run(4) == 'poll' and run.byte('scroll') == 0
    checks += 1
    for zero_run in (2,255):
        run = Run(zero_run=zero_run)
        assert run.run() == 'poll' and run.setup
        checks += 1
    for position in (0x77, 0x95, 0xb2):
        run = Run(screen_position=position)
        assert run.run() == 'poll' and run.hold == position
        checks += 1
    run = Run(cmos_error=True)
    assert run.run() == 'poll' and run.hold is None
    checks += 1
    run = Run(ports_error=True)
    assert run.run() == 'exit' and run.setup and run.hold is None
    checks += 1
    for kwargs in ({'size':0}, {'size':6}, {'zero_run':0}, {'size':65537}, {'short_read':True}, {'bios_error':True},
                   {'version':(0x146,997)}, {'bad_header':True}):
        run = Run(**kwargs)
        assert run.run() == 'exit' and not run.setup, kwargs
        assert 'setup error' in run.message
        checks += 1
    print('%d executable Z80 diagnostic scenarios passed (DSS/BIOS stubs; FPGA not simulated).' % checks)


if __name__ == '__main__': main()
