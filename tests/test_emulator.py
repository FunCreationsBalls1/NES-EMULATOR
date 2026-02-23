from __future__ import annotations

import subprocess
import sys

from nes_emulator import Bus, CPU, Cartridge
from nes_emulator.web import run_rom_bytes


OVERFLOW = 0x40
NEGATIVE = 0x80
ZERO = 0x02
CARRY = 0x01


def make_rom(prg_payload: bytes, flags6: int = 0, flags7: int = 0, prg_banks: int = 1) -> bytes:
    header = bytearray(b"NES\x1a")
    header.extend([prg_banks, 0, flags6, flags7])
    header.extend(b"\x00" * 8)

    prg = bytearray([0xEA] * 16384)
    prg[: len(prg_payload)] = prg_payload

    # Reset vector points to $8000.
    prg[0x3FFC] = 0x00
    prg[0x3FFD] = 0x80
    return bytes(header + prg)


def run_program(program: bytes) -> CPU:
    cart = Cartridge.from_bytes(make_rom(program))
    cpu = CPU(Bus(cart))
    cpu.reset()
    while True:
        used = cpu.step()
        if used == 0:
            break
        cpu.bus.tick(used)
    return cpu


def test_load_and_run_small_program() -> None:
    cpu = run_program(bytes([0xA9, 0x05, 0x69, 0x03, 0xAA, 0xE8, 0x00]))
    assert cpu.a == 0x08
    assert cpu.x == 0x09


def test_indirect_addressing_modes_work() -> None:
    # Set ZP pointers, then load through (zp,X) and (zp),Y and store back.
    cpu = run_program(
        bytes(
            [
                0xA9,
                0x34,
                0x85,
                0x20,  # $20 low
                0xA9,
                0x12,
                0x85,
                0x21,  # $21 high => $1234
                0xA9,
                0x99,
                0x8D,
                0x34,
                0x12,  # mem[$1234] = 0x99
                0xA2,
                0x00,
                0xA1,
                0x20,  # LDA ($20,X) => 0x99
                0xA9,
                0x35,
                0x85,
                0x30,
                0xA9,
                0x12,
                0x85,
                0x31,  # ($30) = $1235
                0xA9,
                0x99,
                0xA0,
                0x00,
                0x91,
                0x30,  # STA ($30),Y -> mem[$1235] = 0x99
                0x00,
            ]
        )
    )

    assert cpu.a == 0x99
    assert cpu.bus.read(0x1234) == 0x99
    assert cpu.bus.read(0x1235) == 0x99


def test_bit_inc_dec_shift_rotate_paths() -> None:
    cpu = run_program(
        bytes(
            [
                0xA9,
                0xC0,
                0x85,
                0x10,  # mem[$10] = 0xC0
                0xA9,
                0x40,
                0x24,
                0x10,  # BIT $10 -> V=1, N=1, Z=0
                0xE6,
                0x10,  # INC $10 -> 0xC1
                0xC6,
                0x10,  # DEC $10 -> 0xC0
                0xA9,
                0x81,
                0x0A,  # ASL A -> 0x02, C=1
                0x6A,  # ROR A -> 0x81
                0x4A,  # LSR A -> 0x40
                0x2A,  # ROL A -> 0x80
                0x00,
            ]
        )
    )

    assert cpu.get_flag(OVERFLOW)
    assert cpu.get_flag(NEGATIVE)
    assert not cpu.get_flag(ZERO)
    assert cpu.a == 0x81


def test_jmp_indirect_page_wrap_bug_behavior() -> None:
    # Build manually so vector at $80FF reads hi byte from $8000 due to 6502 bug.
    prg = bytearray([0xEA] * 16384)
    prg[0x0000] = 0x90  # value used as high byte when ptr is $80FF
    prg[0x00FF] = 0x34  # low byte
    prg[0x0100] = 0x12  # would be used on a bug-free CPU
    # program at $8001
    prg[0x0001:0x0005] = bytes([0x6C, 0xFF, 0x80, 0x00])  # JMP ($80FF), BRK fallback
    # at target $9034 place BRK
    prg[0x1034] = 0x00
    # reset vector to $8001
    prg[0x3FFC] = 0x01
    prg[0x3FFD] = 0x80

    rom = bytes(bytearray(b"NES\x1a") + bytearray([1, 0, 0, 0]) + bytearray(8) + prg)
    cpu = CPU(Bus(Cartridge.from_bytes(rom)))
    cpu.reset()
    while True:
        used = cpu.step()
        if used == 0:
            break
        cpu.bus.tick(used)

    assert cpu.pc == 0x9035


def test_sbc_sets_overflow_and_negative_flags() -> None:
    cpu = run_program(bytes([0x38, 0xA9, 0x80, 0xE9, 0x01, 0x00]))
    assert cpu.a == 0x7F
    assert cpu.get_flag(OVERFLOW)
    assert not cpu.get_flag(NEGATIVE)


def test_logic_and_compare_flags() -> None:
    cpu = run_program(bytes([0xA9, 0xF0, 0x29, 0x0F, 0x09, 0x80, 0x49, 0x80, 0xC9, 0x00, 0x00]))
    assert cpu.a == 0
    assert cpu.get_flag(ZERO)
    assert cpu.get_flag(CARRY)


def test_cli_runs_until_brk(tmp_path) -> None:
    rom_path = tmp_path / "tiny.nes"
    rom_path.write_bytes(make_rom(bytes([0xA9, 0x01, 0x00])))
    result = subprocess.run(
        [sys.executable, "-m", "nes_emulator.cli", str(rom_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Program terminated by BRK" in result.stdout


def test_16k_prg_mirroring() -> None:
    rom = make_rom(bytes([0x00]))
    cart = Cartridge.from_bytes(rom)
    assert cart.cpu_read(0x8000) == cart.cpu_read(0xC000)


def test_rejects_non_nrom_mapper() -> None:
    rom = make_rom(bytes([0x00]), flags6=0x10)
    try:
        Cartridge.from_bytes(rom)
    except ValueError as exc:
        assert "Only mapper 0 and 2 supported" in str(exc)
    else:
        raise AssertionError("Expected non-NROM mapper to be rejected")


def test_web_runner_executes_rom_and_returns_cpu_state() -> None:
    result = run_rom_bytes(make_rom(bytes([0xA9, 0x2A, 0x00])), include_trace=True)
    assert result.termination == "program terminated by BRK"
    assert result.cpu_state["A"] == 0x2A
    assert result.steps == 2
    assert len(result.trace) == 2


def test_mapper2_bank_switching() -> None:
    # 3 PRG banks: bank0 has LDA #$11, bank1 has LDA #$22, bank2 fixed with BRK+vectors.
    prg = bytearray([0xEA] * (3 * 16384))
    prg[0x0000:0x0003] = bytes([0xA9, 0x11, 0x00])
    prg[0x4000:0x4003] = bytes([0xA9, 0x22, 0x00])
    prg[0x8000] = 0x00
    # reset -> $8000
    prg[0xBFFC] = 0x00
    prg[0xBFFD] = 0x80

    header = bytearray(b"NES\x1a")
    # mapper 2 => flags6 high nibble 0x2
    header.extend([3, 0, 0x20, 0x00])
    header.extend(b"\x00" * 8)
    rom = bytes(header + prg)

    cart = Cartridge.from_bytes(rom)
    bus = Bus(cart)

    assert bus.read(0x8001) == 0x11
    bus.write(0x8000, 0x01)
    assert bus.read(0x8001) == 0x22


def test_controller_serial_reading() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)
    bus.controller1.set_buttons(a=True, start=True, right=True)

    # Strobe sequence: high then low to latch buttons.
    bus.write(0x4016, 1)
    bus.write(0x4016, 0)

    reads = [bus.read(0x4016) for _ in range(8)]
    assert reads == [1, 0, 0, 1, 0, 0, 0, 1]


def test_ppu_status_read_clears_vblank() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)
    # Advance to vblank start (scanline 241)
    bus.tick((341 * 241) // 3 + 1)
    assert bus.ppu.status & 0x80
    status = bus.read(0x2002)
    assert status & 0x80
    assert (bus.ppu.status & 0x80) == 0


def test_nmi_is_triggered_from_ppu_vblank() -> None:
    # Program: enable NMI via PPUCTRL then spin forever.
    payload = bytearray([0xA9, 0x80, 0x8D, 0x00, 0x20, 0x4C, 0x05, 0x80])
    prg = bytearray([0xEA] * 16384)
    prg[: len(payload)] = payload

    # NMI routine at $9000: LDA #$42 ; BRK
    nmi_offset = 0x1000
    prg[nmi_offset : nmi_offset + 3] = bytes([0xA9, 0x42, 0x00])

    # vectors
    prg[0x3FFA] = 0x00
    prg[0x3FFB] = 0x90
    prg[0x3FFC] = 0x00
    prg[0x3FFD] = 0x80

    rom = bytes(bytearray(b"NES\x1a") + bytearray([1, 0, 0, 0]) + bytearray(8) + prg)
    cpu = CPU(Bus(Cartridge.from_bytes(rom)))
    cpu.reset()

    for _ in range(40000):
        used = cpu.step()
        if used == 0:
            break
        cpu.bus.tick(used)
    else:
        raise AssertionError("Expected BRK from NMI handler")

    assert cpu.a == 0x42


def test_ppu_addr_data_roundtrip_and_increment() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)

    # Write two bytes to VRAM starting at $2000 using PPUDATA auto-increment by 1.
    bus.write(0x2006, 0x20)
    bus.write(0x2006, 0x00)
    bus.write(0x2007, 0x12)
    bus.write(0x2007, 0x34)

    # Read back via buffered PPUDATA behavior: first read is old buffer, then actual bytes.
    bus.write(0x2006, 0x20)
    bus.write(0x2006, 0x00)
    _ = bus.read(0x2007)
    assert bus.read(0x2007) == 0x12
    assert bus.read(0x2007) == 0x34


def test_ppu_ctrl_increment_32_mode() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)

    bus.write(0x2000, 0x04)  # increment by 32
    bus.write(0x2006, 0x20)
    bus.write(0x2006, 0x00)
    bus.write(0x2007, 0xAA)
    bus.write(0x2007, 0xBB)

    assert bus.ppu.vram[0x000] == 0xAA
    assert bus.ppu.vram[0x020] == 0xBB


def test_ppu_scroll_and_addr_write_toggle_reset_by_status_read() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)

    bus.write(0x2005, 0x15)
    assert bus.ppu.write_toggle
    _ = bus.read(0x2002)
    assert not bus.ppu.write_toggle

    bus.write(0x2006, 0x21)
    bus.write(0x2006, 0x05)
    assert bus.ppu.vram_addr == 0x2105


def test_ppu_oam_addr_data_access() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)

    bus.write(0x2003, 0x10)
    bus.write(0x2004, 0xAB)
    bus.write(0x2004, 0xCD)

    bus.write(0x2003, 0x10)
    assert bus.read(0x2004) == 0xAB
    bus.write(0x2003, 0x11)
    assert bus.read(0x2004) == 0xCD


def test_oam_dma_copies_cpu_page_into_ppu_oam() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)

    # Fill CPU RAM page $0200-$02FF with a pattern.
    for i in range(256):
        bus.write(0x0200 + i, (i * 3) & 0xFF)

    bus.write(0x2003, 0x00)
    bus.write(0x4014, 0x02)

    assert bus.ppu.oam[0x00] == 0x00
    assert bus.ppu.oam[0x01] == 0x03
    assert bus.ppu.oam[0x80] == ((0x80 * 3) & 0xFF)
    assert bus.ppu.oam[0xFF] == ((0xFF * 3) & 0xFF)
    assert bus.dma_cycles == 513


def test_reading_4014_is_open_bus_zero() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)
    assert bus.read(0x4014) == 0


def test_cpu_consumes_dma_stall_cycles() -> None:
    # Program writes to $4014 then BRK. CPU step after DMA write should consume stall cycles.
    program = bytes([0xA9, 0x02, 0x8D, 0x14, 0x40, 0x00])
    cart = Cartridge.from_bytes(make_rom(program))
    cpu = CPU(Bus(cart))
    cpu.reset()

    used1 = cpu.step()
    cpu.bus.tick(used1)
    used2 = cpu.step()
    cpu.bus.tick(used2)

    # Next step should be DMA stall instead of fetching BRK immediately.
    stall = cpu.step()
    assert stall == 513
    cpu.bus.tick(stall)

    used4 = cpu.step()
    assert used4 == 0


def test_ppu_palette_mirror_3f10_to_3f00() -> None:
    cart = Cartridge.from_bytes(make_rom(bytes([0x00])))
    bus = Bus(cart)

    bus.write(0x2006, 0x3F)
    bus.write(0x2006, 0x10)
    bus.write(0x2007, 0x2A)

    bus.write(0x2006, 0x3F)
    bus.write(0x2006, 0x00)
    assert bus.read(0x2007) == 0x2A


def test_ppu_nametable_vertical_mirroring() -> None:
    # flags6 bit0=1 => vertical mirroring
    cart = Cartridge.from_bytes(make_rom(bytes([0x00]), flags6=0x01))
    bus = Bus(cart)

    # $2000 and $2800 are mirrored in vertical mode.
    bus.write(0x2006, 0x20)
    bus.write(0x2006, 0x00)
    bus.write(0x2007, 0x66)

    bus.write(0x2006, 0x28)
    bus.write(0x2006, 0x00)
    _ = bus.read(0x2007)
    assert bus.read(0x2007) == 0x66


def test_ppu_nametable_horizontal_mirroring() -> None:
    # default flags6 bit0=0 => horizontal mirroring
    cart = Cartridge.from_bytes(make_rom(bytes([0x00]), flags6=0x00))
    bus = Bus(cart)

    # $2000 and $2400 are mirrored in horizontal mode.
    bus.write(0x2006, 0x20)
    bus.write(0x2006, 0x00)
    bus.write(0x2007, 0x77)

    bus.write(0x2006, 0x24)
    bus.write(0x2006, 0x00)
    _ = bus.read(0x2007)
    assert bus.read(0x2007) == 0x77
