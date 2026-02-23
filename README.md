# NES-EMULATOR

A tiny **from-scratch NES emulator core** written in Python.

This project intentionally focuses on a minimal, understandable baseline:

- iNES ROM loader
- Mapper 0 (NROM) and mapper 2 (UNROM) PRG-ROM support
- CPU bus with mirrored 2KB RAM
- A larger 6502 CPU subset with common addressing modes and stack/branch support
- CLI runner with optional instruction trace
- Browser-based ROM runner (upload + execute ROM from a website)
- Controller ($4016/$4017) serial input emulation
- Basic PPU timing + VBlank/NMI signaling
- PPU register emulation for `PPUCTRL/PPUSTATUS/PPUSCROLL/PPUADDR/PPUDATA`
- OAM register + OAM DMA (`$2003/$2004/$4014`)
- OAM DMA cycle stall bookkeeping (513-cycle DMA penalty surfaced to CPU core)
- Nametable mirroring (horizontal/vertical) + palette mirror handling
- APU frame counter/status register skeleton with IRQ generation
- CPU IRQ polling + RTI opcode support

> Status: educational prototype, now with mapper 2 + controller IO + basic PPU vblank/NMI timing, but still not a full NES emulator.

## Quick start

```bash
python -m pip install -e .
nes-emulator path/to/game.nes --trace

# Web UI (open http://localhost:8000)
nes-emulator-web --port 8000
```

## One-command setup and run

```bash
./run_emulator.sh
```

This command will:
- create a local `.venv` (if missing),
- install/update dependencies,
- install this project in editable mode,
- launch the web emulator at `http://localhost:8000`.

Other modes:

```bash
./run_emulator.sh cli path/to/game.nes
./run_emulator.sh setup-only
```

## Implemented CPU opcodes

`NOP, LDA, LDX, LDY, STA, STX, STY, TAX, TAY, TXA, TYA, TSX, TXS, PHA, PLA, PHP, PLP, INX, INY, DEX, DEY, INC, DEC, ADC, SBC, AND, ORA, EOR, BIT, CMP, CPX, CPY, ASL, LSR, ROL, ROR, CLC, SEC, CLI, SEI, CLV, CLD, SED, JMP (abs/ind), JSR, RTS, BNE, BEQ, BCC, BCS, BPL, BMI, BVC, BVS, BRK`

## Development

```bash
python -m pip install pytest
pytest
```


## Web runner

The web runner provides a simple website where users can upload a `.nes` ROM and run it directly in the emulator core.

- Start server: `nes-emulator-web --port 8000`
- Open: `http://localhost:8000`
- Upload ROM and click **Run ROM**

This now executes the CPU core and renders a 256x240 frame preview in the browser (plus register/trace output).
