from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Cartridge:
    """Minimal iNES parser with mapper 0 (NROM) + mapper 2 (UNROM) support."""

    prg_rom: bytes
    chr_rom: bytes
    mapper: int
    mirroring: str
    prg_banks: int
    prg_bank_select: int = 0

    @classmethod
    def from_bytes(cls, rom: bytes) -> "Cartridge":
        if len(rom) < 16:
            raise ValueError("ROM too small to contain iNES header")

        header = rom[:16]
        if header[:4] != b"NES\x1a":
            raise ValueError("Not a valid iNES ROM")

        prg_banks = header[4]
        chr_banks = header[5]
        flags6 = header[6]
        flags7 = header[7]

        mapper = (flags6 >> 4) | (flags7 & 0xF0)
        if mapper not in (0, 2):
            raise ValueError(f"Only mapper 0 and 2 supported, got mapper {mapper}")

        has_trainer = bool(flags6 & 0b100)
        mirroring = "vertical" if flags6 & 0b1 else "horizontal"

        offset = 16 + (512 if has_trainer else 0)
        prg_size = prg_banks * 16384
        chr_size = chr_banks * 8192

        end = offset + prg_size + chr_size
        if len(rom) < end:
            raise ValueError("ROM truncated")

        prg_rom = rom[offset : offset + prg_size]
        chr_rom = rom[offset + prg_size : end] if chr_size else bytes(8192)

        return cls(
            prg_rom=prg_rom,
            chr_rom=chr_rom,
            mapper=mapper,
            mirroring=mirroring,
            prg_banks=prg_banks,
        )

    @classmethod
    def from_file(cls, path: str) -> "Cartridge":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def cpu_read(self, addr: int) -> int:
        if addr < 0x8000:
            raise ValueError(f"Cartridge read out of range: {addr:#06x}")

        if self.mapper == 0:
            offset = addr - 0x8000
            if len(self.prg_rom) == 16384:
                offset %= 16384
            return self.prg_rom[offset]

        # Mapper 2 (UNROM): $8000-$BFFF switchable, $C000-$FFFF fixed to last bank.
        bank_size = 16384
        if addr < 0xC000:
            bank = self.prg_bank_select % max(self.prg_banks, 1)
            offset = bank * bank_size + (addr - 0x8000)
            return self.prg_rom[offset]

        last_bank = max(self.prg_banks - 1, 0)
        offset = last_bank * bank_size + (addr - 0xC000)
        return self.prg_rom[offset]

    def cpu_write(self, addr: int, value: int) -> None:
        if addr < 0x8000:
            return
        if self.mapper == 2:
            self.prg_bank_select = value & 0x0F
