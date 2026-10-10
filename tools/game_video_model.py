"""Executable specification, not an AHDL/netlist simulator.

One step is one CLK42 rising edge followed by SRAM settling. Banks are
VDM0..3; logical byte zero resides in VDM3. SRAM latency is configurable.
"""
from dataclasses import dataclass

PHASES = (0, 1, 2, 4, 5, 6)
VCM = {0: 5, 1: 1, 2: 4, 4: 3, 5: 2, 6: 0}
PERIOD_NS = 1000 / 42


def descriptor_address(page, x, y):
    return (page << 17) | ((x // 8) << 11) | 0x700 | ((y // 8) << 2)


def pixel_address(mode, x, y):
    return ((((mode[2] + y) & 255) * 1024) +
            ((mode[0] & 3) << 8) + mode[1] + x) & 0x3ffff


def palette_address(index):
    return ((index & 255) << 10) | 0x3e0 | ((index >> 8) << 2)


class SRAM:
    def __init__(self, latency_ns=15, address_delay_ns=0, fpga_input_delay_ns=0,
                 dac_setup_ns=0):
        self.banks = [bytearray(65536) for _ in range(4)]
        self.latency_ns = latency_ns
        # Explicit test budgets, NOT fitted/board measurements. Address delay
        # includes FPGA clock-to-pin and board flight time; FPGA input delay
        # includes return routing, bank mux and register setup. The external
        # RGB registers have a different input/setup path.
        self.address_delay_ns = address_delay_ns
        self.fpga_input_delay_ns = fpga_input_delay_ns
        self.dac_setup_ns = dac_setup_ns
        self.address = 0
        self.issued_ns = -100

    def write(self, address, value):
        self.banks[3 - (address & 3)][(address & 0x3ffff) >> 2] = value

    def load(self, address, data):
        for offset, value in enumerate(data):
            self.write(address + offset, value)

    def issue(self, address, now):
        word = (address & 0x3ffff) >> 2
        # VA has no byte-select bits. Holding the same word does not restart
        # an asynchronous read, including a second registered address slot.
        if word != self.address:
            self.address = word
            self.issued_ns = now

    def read_banks(self, now, receiver='fpga'):
        setup = {'fpga': self.fpga_input_delay_ns, 'dac': self.dac_setup_ns}[receiver]
        if now - self.issued_ns + 1e-6 < self.address_delay_ns + self.latency_ns + setup:
            raise RuntimeError('SRAM setup time not satisfied')
        return tuple(bank[self.address] for bank in self.banks)


@dataclass
class Sample:
    x: int
    y: int
    descriptor: int
    address: int
    bank: int
    color: int
    palette: int
    blank: bool
    irq: bool


class Video:
    def __init__(self, ram):
        self.ram = ram
        # A new controller starts a new simulation timeline. Keep memory
        # contents, but reset the address-register power-up state and age.
        ram.address, ram.issued_ns = 0, -100
        self.phase = 0
        self.x = self.y = self.now = 0
        self.scroll = self.page = self.border = 0
        self.screen_off = False
        self.last = None
        self.mode = (0, 0, 0, 0)
        self.request = self.local_x = self.local_y = 0
        self.fetch_x = self.fetch_y = 0
        self.palette = 0
        self.sample = None
        self.pending = None
        self.acceptances = 0
        self.scroll_loads = 0
        self.cpu_address = 0x23450
        self.cpu_write = None
        self.slots = []
        self.rgb = None
        self.rgb_clocks = 0

    def step(self):
        phase = self.phase
        result = None
        if phase == 0:
            # 74HC374 rising edge: old palette is still on the bus before
            # VLA changes to the pixel address. Same-edge hold is a separate
            # physical timing requirement, not proved by this setup model.
            self.rgb = self.ram.read_banks(self.now, receiver='dac')[1:]
            self.rgb_clocks += 1
        if phase == 2:
            address = pixel_address(self.mode, self.local_x, self.local_y)
            banks = self.ram.read_banks(self.now)
            bank = 3 - (address & 3)
            color = banks[bank]
            border = self.mode[0] >> 5 == 7
            blank = (border and self.mode[0] & 12 == 12) or self.screen_off
            irq = border and self.mode[0] & 13 == 13
            self.palette = (0x400 if blank else
                            0x400 | self.border * 9 if border else
                            (self.mode[0] >> 6) * 256 + color)
            result = self.sample = Sample(self.fetch_x, self.fetch_y, self.request,
                                         address, bank, color, self.palette, bool(blank), bool(irq))
            # Physical CTV increments at the end of CTH=48 (not at X wrap).
            nx = (self.x + 1) % 448
            if self.local_x == 7 and self.pending is not None:
                self.scroll = self.pending
                self.pending = None
                self.scroll_loads += 1
            ny = (self.y + (self.x == 391)) % 320
            self.fetch_x = (nx + (self.scroll & 15)) % 448
            self.fetch_y = (ny + (self.scroll >> 4)) % 320
            self.local_x, self.local_y = self.fetch_x & 7, self.fetch_y & 7
            self.request = descriptor_address(self.page, self.fetch_x, self.fetch_y)
            address, slot = self.request, 'descriptor'
        elif phase == 4:
            address, slot = self.request, 'descriptor'
        elif phase == 5:
            banks = self.ram.read_banks(self.now)
            self.mode = banks[::-1]
            if self.last != self.request:
                self.acceptances += 1
                if self.mode[0] & 4:
                    self.pending = self.mode[3]
            self.last = self.request
            address, slot = self.cpu_address, 'cpu'
            if self.cpu_write is not None:
                self.ram.write(address, self.cpu_write)
        elif phase in (0, 1):
            address = pixel_address(self.mode, self.local_x, self.local_y)
            slot = 'pixel'
        else:
            address, slot = palette_address(self.palette), 'palette'
        self.ram.issue(address, self.now)
        self.slots.append((phase, slot, address))
        if len(self.slots) > 12:
            del self.slots[:6]
        if phase == 6:
            self.y = (self.y + (self.x == 391)) % 320
            self.x = (self.x + 1) % 448
        self.phase = PHASES[(PHASES.index(phase) + 1) % 6]
        self.now += PERIOD_NS
        return result

    def next_sample(self):
        while True:
            sample = self.step()
            if sample is not None:
                return sample
