from __future__ import annotations

from dataclasses import dataclass, field

from .cartridge import Cartridge
from .controller import Controller
from .ppu import PPU


@dataclass
class Bus:
    """NES CPU bus with RAM mirroring, PPU regs/timing, controller IO, and cartridge mapping."""

    cartridge: Cartridge
    ram: bytearray = field(default_factory=lambda: bytearray(2048))
    controller1: Controller = field(default_factory=Controller)
    controller2: Controller = field(default_factory=Controller)
    ppu: PPU = field(default_factory=PPU)
    nmi_pending: bool = False
    dma_cycles: int = 0

    def __post_init__(self) -> None:
        self.ppu.mirroring = self.cartridge.mirroring

    def read(self, addr: int) -> int:
        addr &= 0xFFFF
        if addr < 0x2000:
            return self.ram[addr % 0x0800]
        if 0x2000 <= addr < 0x4000:
            reg = 0x2000 + (addr % 8)
            if reg == 0x2002:
                return self.ppu.read_status()
            if reg == 0x2004:
                return self.ppu.read_oam_data()
            if reg == 0x2007:
                return self.ppu.read_data()
            return 0
        if addr == 0x4016:
            return self.controller1.read()
        if addr == 0x4017:
            return self.controller2.read()
        if addr >= 0x8000:
            return self.cartridge.cpu_read(addr)
        return 0

    def write(self, addr: int, value: int) -> None:
        addr &= 0xFFFF
        value &= 0xFF
        if addr < 0x2000:
            self.ram[addr % 0x0800] = value
            return
        if 0x2000 <= addr < 0x4000:
            reg = 0x2000 + (addr % 8)
            if reg == 0x2000:
                self.ppu.write_ctrl(value)
            elif reg == 0x2001:
                self.ppu.write_mask(value)
            elif reg == 0x2003:
                self.ppu.write_oam_addr(value)
            elif reg == 0x2004:
                self.ppu.write_oam_data(value)
            elif reg == 0x2005:
                self.ppu.write_scroll(value)
            elif reg == 0x2006:
                self.ppu.write_addr(value)
            elif reg == 0x2007:
                self.ppu.write_data(value)
            return
        if addr == 0x4014:
            start = value << 8
            page = bytes(self.read((start + i) & 0xFFFF) for i in range(256))
            self.ppu.oam_dma_write(page)
            self.dma_cycles += 513
            return
        if addr == 0x4016:
            self.controller1.write_strobe(value)
            self.controller2.write_strobe(value)
            if value & 1 == 0:
                self.controller1.latch()
                self.controller2.latch()
            return
        if addr >= 0x8000:
            self.cartridge.cpu_write(addr, value)

    def consume_dma_cycles(self) -> int:
        cycles = self.dma_cycles
        self.dma_cycles = 0
        return cycles

    def tick(self, cpu_cycles: int) -> None:
        if self.ppu.step(cpu_cycles * 3):
            self.nmi_pending = True

    def poll_nmi(self) -> bool:
        pending = self.nmi_pending
        self.nmi_pending = False
        return pending

    def read_u16(self, addr: int) -> int:
        lo = self.read(addr)
        hi = self.read((addr + 1) & 0xFFFF)
        return lo | (hi << 8)
