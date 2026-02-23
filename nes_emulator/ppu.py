from __future__ import annotations

from dataclasses import dataclass, field


VBLANK_FLAG = 0x80
NMI_ENABLE = 0x80
VRAM_ADDR_INCREMENT = 0x04


@dataclass
class PPU:
    """Very small timing + register PPU model for VBlank/NMI and VRAM IO behavior."""

    ctrl: int = 0
    mask: int = 0
    status: int = 0
    oam_addr: int = 0
    cycle: int = 0
    scanline: int = 0
    frame: int = 0

    vram_addr: int = 0
    temp_addr: int = 0
    fine_x: int = 0
    write_toggle: bool = False
    data_buffer: int = 0

    vram: bytearray = field(default_factory=lambda: bytearray(0x800))
    palette: bytearray = field(default_factory=lambda: bytearray(0x20))
    oam: bytearray = field(default_factory=lambda: bytearray(256))
    mirroring: str = "horizontal"

    def vram_increment(self) -> int:
        return 32 if (self.ctrl & VRAM_ADDR_INCREMENT) else 1

    def write_ctrl(self, value: int) -> None:
        self.ctrl = value & 0xFF
        self.temp_addr = (self.temp_addr & 0xF3FF) | ((value & 0x03) << 10)

    def write_mask(self, value: int) -> None:
        self.mask = value & 0xFF

    def write_scroll(self, value: int) -> None:
        if not self.write_toggle:
            self.fine_x = value & 0x07
            self.temp_addr = (self.temp_addr & 0xFFE0) | (value >> 3)
            self.write_toggle = True
            return
        self.temp_addr = (self.temp_addr & 0x8C1F) | ((value & 0x07) << 12) | ((value & 0xF8) << 2)
        self.write_toggle = False

    def write_addr(self, value: int) -> None:
        if not self.write_toggle:
            self.temp_addr = (self.temp_addr & 0x00FF) | ((value & 0x3F) << 8)
            self.write_toggle = True
            return
        self.temp_addr = (self.temp_addr & 0xFF00) | value
        self.vram_addr = self.temp_addr & 0x3FFF
        self.write_toggle = False

    def read_status(self) -> int:
        value = self.status
        self.status &= ~VBLANK_FLAG
        self.write_toggle = False
        return value

    def read_data(self) -> int:
        addr = self.vram_addr & 0x3FFF
        self.vram_addr = (self.vram_addr + self.vram_increment()) & 0x3FFF

        if addr >= 0x3F00:
            # Palette reads are not delayed, but buffer updates from mirrored nametable space.
            self.data_buffer = self._vram_read(addr - 0x1000)
            return self._vram_read(addr)

        value = self.data_buffer
        self.data_buffer = self._vram_read(addr)
        return value

    def write_data(self, value: int) -> None:
        addr = self.vram_addr & 0x3FFF
        self._vram_write(addr, value & 0xFF)
        self.vram_addr = (self.vram_addr + self.vram_increment()) & 0x3FFF

    def _palette_index(self, addr: int) -> int:
        idx = addr & 0x1F
        if idx in (0x10, 0x14, 0x18, 0x1C):
            idx -= 0x10
        return idx

    def _nametable_index(self, addr: int) -> int:
        rel = (addr - 0x2000) & 0x0FFF
        table = rel // 0x400
        offset = rel % 0x400

        if self.mirroring == "vertical":
            phys = table % 2
        else:  # horizontal
            phys = 0 if table in (0, 1) else 1
        return phys * 0x400 + offset

    def _vram_read(self, addr: int) -> int:
        if 0x2000 <= addr <= 0x3EFF:
            return self.vram[self._nametable_index(addr)]
        if addr >= 0x3F00:
            return self.palette[self._palette_index(addr)]
        return 0

    def _vram_write(self, addr: int, value: int) -> None:
        if 0x2000 <= addr <= 0x3EFF:
            self.vram[self._nametable_index(addr)] = value
            return
        if addr >= 0x3F00:
            self.palette[self._palette_index(addr)] = value


    def write_oam_addr(self, value: int) -> None:
        self.oam_addr = value & 0xFF

    def read_oam_data(self) -> int:
        return self.oam[self.oam_addr]

    def write_oam_data(self, value: int) -> None:
        self.oam[self.oam_addr] = value & 0xFF
        self.oam_addr = (self.oam_addr + 1) & 0xFF

    def oam_dma_write(self, values: bytes) -> None:
        for b in values:
            self.oam[self.oam_addr] = b
            self.oam_addr = (self.oam_addr + 1) & 0xFF

    def step(self, ppu_cycles: int) -> bool:
        """Advance PPU timing. Returns True when an NMI should be fired."""
        nmi_triggered = False
        for _ in range(ppu_cycles):
            self.cycle += 1
            if self.cycle > 340:
                self.cycle = 0
                self.scanline += 1

                if self.scanline == 241:
                    self.status |= VBLANK_FLAG
                    if self.ctrl & NMI_ENABLE:
                        nmi_triggered = True
                elif self.scanline >= 262:
                    self.scanline = 0
                    self.frame += 1
                    self.status &= ~VBLANK_FLAG
        return nmi_triggered
