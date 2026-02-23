from __future__ import annotations

import argparse

from . import Bus, CPU, Cartridge


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a tiny from-scratch NES CPU emulator.")
    parser.add_argument("rom", help="Path to iNES ROM (mapper 0)")
    parser.add_argument("--max-steps", type=int, default=200000, help="Instruction step budget")
    parser.add_argument("--trace", action="store_true", help="Print simple CPU trace")
    args = parser.parse_args()

    cart = Cartridge.from_file(args.rom)
    bus = Bus(cart)
    cpu = CPU(bus)
    cpu.reset()

    steps = 0
    while steps < args.max_steps:
        pc_before = cpu.pc
        opcode = bus.read(pc_before)
        used = cpu.step()
        if used:
            bus.tick(used)
        if args.trace:
            print(
                f"PC={pc_before:04X} OP={opcode:02X} A={cpu.a:02X} X={cpu.x:02X} "
                f"Y={cpu.y:02X} P={cpu.p:02X} SP={cpu.sp:02X} CYC={cpu.cycles}"
            )
        steps += 1
        if used == 0:
            print(f"Program terminated by BRK after {steps} steps, {cpu.cycles} cycles")
            return

    print(f"Step budget exhausted ({args.max_steps})")


if __name__ == "__main__":
    main()
