#!/usr/bin/env python3
"""Execute external TITDREV startup and the actual BIOS bit sender on Z80.

Requires the reconstructed TITD source/build and BIOS source supplied explicitly;
no external trees are modified. API services and configuration pins are simulated.
This tests container compatibility, not FPGA compilation or operation.
"""
import argparse
import hashlib
import importlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
HEADER = bytes.fromhex('ffff627b3c00')


def unpack(data):
    if not 1 <= len(data) <= 65536: raise ValueError('ACX must fit 1..4 pages of 16 KiB')
    out = bytearray(); pos = 0
    while pos < len(data):
        byte = data[pos]; pos += 1
        if byte: out.append(byte)
        else:
            if pos == len(data) or data[pos] == 0: raise ValueError('Invalid zero-run')
            out.extend(bytes(data[pos])); pos += 1
    if not out.startswith(HEADER): raise ValueError('ACX is not a packed K50 stream at offset zero')
    return bytes(out)


def bios_sender(bios, tmp, encoded, raw):
    """Assemble the source header check and byte/bit sender, without rewriting it."""
    from z80 import Z80Machine
    source = (bios/'src/bios/loader/loader.asm').read_text(encoding='cp866')
    check = source[source.index('.NEW_SHM:'):source.index(';---------------------------------------', source.index('.NEW_SHM:'))]
    loop = source[source.index('.LOOP1:'):source.index('.STRING:')]
    # The source .Conf_header is the ROM's uncompressed K30 signature. K50
    # packed data must take .Conf_Packed, then the unmodified zero-run sender.
    header = (bios/'src/bios/loader/bitstream_header.inc').read_text(encoding='cp866')
    asm = tmp/'sender.asm'; exe = tmp/'sender.bin'
    asm.write_text('    ORG #2000\nLoad:\n' + check + '\n    LD DE,#FE00\n' + loop + '\n.Conf_header:\n' + header + '\n.Conf_header.length EQU $-.Conf_header\n')
    subprocess.run(['sjasmplus','--raw='+str(exe),str(asm)],check=True,stdout=subprocess.DEVNULL)
    m = Z80Machine(); m.set_memory_block(0x2000,exe.read_bytes()); m.set_memory_block(0x8000,encoded)
    m.pc = 0x2000; m.hl = 0x8000; m.sp = 0x7ffe; m.alt_af = 0
    bits = []
    class Complete(Exception): pass
    def write(addr,value):
        bits.append(value&1)
        if len(bits) == len(raw)*8: raise Complete()
    m.set_write_callback(write)
    m.mark_addrs(0xfe00,256,4)  # z80 memory write callbacks require a write mark
    try:
        for _ in range(100):
            m.ticks_to_stop = 1_000_000
            m.run()
    except Complete: pass
    expected = [(byte>>bit)&1 for byte in raw for bit in range(8)]
    assert bits == expected, 'BIOS bit order or zero-run expansion differs'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--titd-src',type=Path,required=True)
    ap.add_argument('--bios-root',type=Path,required=True)
    ap.add_argument('--acx',type=Path,help='Also test an actual Windows-built K50.ACX')
    ap.add_argument('--loader-patch',action='store_true',help='Assemble and test the accompanying loader fix in a temporary copy')
    args = ap.parse_args()
    sys.path.insert(0,str(args.titd_src/'tools'))
    mod = importlib.import_module('simulate_reverse_memory')
    mod.ACX_BASE_NAME = b'K50'
    build = args.titd_src/'build'
    runtime = (build/'runtime_image_patched.bin').read_bytes()
    symbols = mod.sim_mod.read_symbols(build/'runtime_image_patched.sym')
    print('TITDREV runtime SHA256:',hashlib.sha256(runtime).hexdigest())
    checks = 0
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name); packer = tmp/'packer'; acx = tmp/'K50.ACX'; rawfile = tmp/'raw'
        subprocess.run(['cc',str(ROOT/'bin/Altera0pak.c'),'-o',str(packer)],check=True)
        if args.loader_patch:
            stage = tmp/'titd'; stage.mkdir()
            for directory in ('include','runtime'): shutil.copytree(args.titd_src/directory,stage/directory)
            (stage/'build').mkdir()
            subprocess.run(['patch','-p1','-i',str(ROOT/'tools/titdrev_acx.patch')],cwd=stage,check=True,stdout=subprocess.DEVNULL)
            subprocess.run(['sjasmplus','--sym=build/runtime_image_patched.sym','runtime/runtime_image_patched.asm'],cwd=stage,check=True,stdout=subprocess.DEVNULL)
            runtime = (stage/'build/runtime_image_patched.bin').read_bytes()
            symbols = mod.sim_mod.read_symbols(stage/'build/runtime_image_patched.sym')
            print('Temporarily patched runtime SHA256:',hashlib.sha256(runtime).hexdigest())
        def launch(encoded, accept=True):
            acx.write_bytes(encoded)
            mem = mod.MemoryModel(mod.GAME_PAGES+mod.EXE_PAGES+2); mem.launch()
            run = mod.Run(SimpleNamespace(acx=acx,pak=build/'TITD.PAK',verbose=False),symbols,runtime,mem)
            run.sim.add_file('K50.ACX',encoded)
            read = run.sim._dss
            def dss_with_unspecified_de():
                reading = run.sim.m.c == mod.sim_mod.DSS_READ
                handle = run.sim.m.a
                read()
                if reading:
                    run.sim.m.de = 0xdead  # caller cannot use this as byte count
                    file = run.sim.files[handle]
                    run.sim.m.a = 255 if file.pos >= len(file.data) else 0
                    run.sim.m.f = (run.sim.m.f & ~0x41) | (0x40 if run.sim.m.a == 0 else 0)
            run.sim._dss = dss_with_unspecified_de
            captured = []
            original = run.sim.bios_extra[mod.BIOS_RST_CONF]
            def config(s):
                if s.m.a == mod.ACEX_SETUP_NOW and s.m.b:
                    pages = mem.chain(s.m.b); s.sync_all()
                    captured.append(b''.join(bytes(s.page(p)) for p in pages))
                original(s)
            run.sim.bios_extra[mod.BIOS_RST_CONF] = config
            assert run.startup() == accept, 'TITDREV acceptance mismatch'
            if accept:
                assert not run.errors, run.errors
                assert len(run.setup_now_pages) == (len(encoded)+16383)//16384
                assert len(captured)==1 and captured[0].startswith(encoded), 'ACX bytes changed in page chain'
                if args.loader_patch:
                    assert captured[0] == encoded+bytes([255])*(-len(encoded)%16384), 'Patched loader did not pad FF'
                # External Reverse code uses ADD HL,BC / JP NZ to detect a
                # partial page. ADD preserves Z, so FF padding is not reliable.
                # Payload is exact; BIOS completion must precede unused tail.
                run.exit_to_dss()
            else: assert not captured, 'Oversized ACX reached AcexSetUpNow'
        for size in (7,16383,16384,16385,32768,49153,65536):
            raw = HEADER+bytes([0xa5])*(size-7)
            rawfile.write_bytes(raw)
            subprocess.run([str(packer),str(rawfile),str(acx)],check=True,stdout=subprocess.DEVNULL)
            encoded = acx.read_bytes()
            assert len(encoded) == size and unpack(encoded) == raw
            launch(encoded); checks += 1
        launch(HEADER[:-1]+b'\x00\x01'+bytes([0xa5])*(65537-7),False); checks += 1
        for count in (1,254,255,256,1024):
            raw = HEADER+bytes(count)+bytes(range(1,256))
            rawfile.write_bytes(raw)
            subprocess.run([str(packer),str(rawfile),str(acx)],check=True,stdout=subprocess.DEVNULL)
            encoded = acx.read_bytes()
            assert unpack(encoded) == raw
            bios_sender(args.bios_root,tmp,encoded,raw); checks += 1
        if args.acx:
            encoded = args.acx.read_bytes(); raw = unpack(encoded)
            launch(encoded); checks += 1
            print('Actual ACX:',len(encoded),'bytes; unpacked:',len(raw),'bytes; SHA256:',hashlib.sha256(encoded).hexdigest())
    print('TITDREV/BIOS compatibility:',checks,'scenarios passed (simulated services/pins)')


if __name__ == '__main__': main()
