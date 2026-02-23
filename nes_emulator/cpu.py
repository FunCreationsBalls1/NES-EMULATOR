from __future__ import annotations

from dataclasses import dataclass

from .bus import Bus


NEGATIVE = 0x80
OVERFLOW = 0x40
UNUSED = 0x20
BREAK = 0x10
DECIMAL = 0x08
INTERRUPT_DISABLE = 0x04
ZERO = 0x02
CARRY = 0x01


@dataclass
class CPU:
    bus: Bus
    a: int = 0
    x: int = 0
    y: int = 0
    p: int = UNUSED | INTERRUPT_DISABLE
    sp: int = 0xFD
    pc: int = 0
    cycles: int = 0

    def reset(self) -> None:
        self.a = self.x = self.y = 0
        self.p = UNUSED | INTERRUPT_DISABLE
        self.sp = 0xFD
        self.pc = self.bus.read_u16(0xFFFC)
        self.cycles = 7

    def fetch(self) -> int:
        value = self.bus.read(self.pc)
        self.pc = (self.pc + 1) & 0xFFFF
        return value

    def fetch_u16(self) -> int:
        lo = self.fetch()
        hi = self.fetch()
        return lo | (hi << 8)

    def zp_addr(self) -> int:
        return self.fetch()

    def zp_x_addr(self) -> int:
        return (self.fetch() + self.x) & 0xFF

    def zp_y_addr(self) -> int:
        return (self.fetch() + self.y) & 0xFF

    def abs_addr(self) -> int:
        return self.fetch_u16()

    def abs_x_addr(self) -> int:
        return (self.fetch_u16() + self.x) & 0xFFFF

    def abs_y_addr(self) -> int:
        return (self.fetch_u16() + self.y) & 0xFFFF

    def indirect_x_addr(self) -> int:
        base = (self.fetch() + self.x) & 0xFF
        lo = self.bus.read(base)
        hi = self.bus.read((base + 1) & 0xFF)
        return lo | (hi << 8)

    def indirect_y_addr(self) -> int:
        base = self.fetch()
        lo = self.bus.read(base)
        hi = self.bus.read((base + 1) & 0xFF)
        return ((lo | (hi << 8)) + self.y) & 0xFFFF

    def jmp_indirect_addr(self) -> int:
        ptr = self.fetch_u16()
        lo = self.bus.read(ptr)
        # Emulate 6502 page-wrap hardware bug.
        hi = self.bus.read((ptr & 0xFF00) | ((ptr + 1) & 0x00FF))
        return lo | (hi << 8)

    def set_zn(self, value: int) -> None:
        value &= 0xFF
        self.set_flag(ZERO, value == 0)
        self.set_flag(NEGATIVE, bool(value & 0x80))

    def set_flag(self, flag: int, enabled: bool) -> None:
        if enabled:
            self.p |= flag
        else:
            self.p &= ~flag
        self.p |= UNUSED

    def get_flag(self, flag: int) -> bool:
        return bool(self.p & flag)

    def push(self, value: int) -> None:
        self.bus.write(0x0100 + self.sp, value)
        self.sp = (self.sp - 1) & 0xFF

    def pop(self) -> int:
        self.sp = (self.sp + 1) & 0xFF
        return self.bus.read(0x0100 + self.sp)

    def adc(self, operand: int) -> None:
        carry_in = 1 if self.get_flag(CARRY) else 0
        total = self.a + operand + carry_in
        result = total & 0xFF
        self.set_flag(CARRY, total > 0xFF)
        overflow = (~(self.a ^ operand) & (self.a ^ result) & 0x80) != 0
        self.set_flag(OVERFLOW, overflow)
        self.a = result
        self.set_zn(self.a)

    def sbc(self, operand: int) -> None:
        operand_inverted = operand ^ 0xFF
        carry_in = 1 if self.get_flag(CARRY) else 0
        total = self.a + operand_inverted + carry_in
        result = total & 0xFF
        self.set_flag(CARRY, total > 0xFF)
        overflow = ((self.a ^ result) & (self.a ^ operand) & 0x80) != 0
        self.set_flag(OVERFLOW, overflow)
        self.a = result
        self.set_zn(self.a)

    def compare(self, register: int, operand: int) -> None:
        result = (register - operand) & 0xFF
        self.set_flag(CARRY, register >= operand)
        self.set_zn(result)

    def bit(self, operand: int) -> None:
        self.set_flag(ZERO, (self.a & operand) == 0)
        self.set_flag(NEGATIVE, bool(operand & 0x80))
        self.set_flag(OVERFLOW, bool(operand & 0x40))

    def branch(self, condition: bool) -> int:
        offset = self.fetch()
        used = 2
        if condition:
            if offset & 0x80:
                offset -= 0x100
            self.pc = (self.pc + offset) & 0xFFFF
            used += 1
        return used

    def asl_value(self, value: int) -> int:
        self.set_flag(CARRY, bool(value & 0x80))
        result = (value << 1) & 0xFF
        self.set_zn(result)
        return result

    def lsr_value(self, value: int) -> int:
        self.set_flag(CARRY, bool(value & 0x01))
        result = (value >> 1) & 0xFF
        self.set_zn(result)
        return result

    def rol_value(self, value: int) -> int:
        carry_in = 1 if self.get_flag(CARRY) else 0
        self.set_flag(CARRY, bool(value & 0x80))
        result = ((value << 1) & 0xFF) | carry_in
        self.set_zn(result)
        return result

    def ror_value(self, value: int) -> int:
        carry_in = 0x80 if self.get_flag(CARRY) else 0
        self.set_flag(CARRY, bool(value & 0x01))
        result = ((value >> 1) & 0x7F) | carry_in
        self.set_zn(result)
        return result

    def handle_nmi(self) -> int:
        self.push((self.pc >> 8) & 0xFF)
        self.push(self.pc & 0xFF)
        flags = self.p & ~BREAK
        self.push(flags)
        self.set_flag(INTERRUPT_DISABLE, True)
        self.pc = self.bus.read_u16(0xFFFA)
        return 7

    def handle_irq(self) -> int:
        self.push((self.pc >> 8) & 0xFF)
        self.push(self.pc & 0xFF)
        flags = self.p & ~BREAK
        self.push(flags)
        self.set_flag(INTERRUPT_DISABLE, True)
        self.pc = self.bus.read_u16(0xFFFE)
        return 7

    def step(self) -> int:
        dma_cycles = self.bus.consume_dma_cycles()
        if dma_cycles:
            self.cycles += dma_cycles
            return dma_cycles

        if self.bus.poll_nmi():
            used = self.handle_nmi()
            self.cycles += used
            return used

        if self.bus.poll_irq() and not self.get_flag(INTERRUPT_DISABLE):
            used = self.handle_irq()
            self.cycles += used
            return used

        opcode = self.fetch()

        if opcode == 0xEA:  # NOP
            used = 2

        # Load/store accumulator
        elif opcode == 0xA9:  # LDA #imm
            self.a = self.fetch()
            self.set_zn(self.a)
            used = 2
        elif opcode == 0xA5:  # LDA zp
            self.a = self.bus.read(self.zp_addr())
            self.set_zn(self.a)
            used = 3
        elif opcode == 0xB5:  # LDA zp,X
            self.a = self.bus.read(self.zp_x_addr())
            self.set_zn(self.a)
            used = 4
        elif opcode == 0xAD:  # LDA abs
            self.a = self.bus.read(self.abs_addr())
            self.set_zn(self.a)
            used = 4
        elif opcode == 0xBD:  # LDA abs,X
            self.a = self.bus.read(self.abs_x_addr())
            self.set_zn(self.a)
            used = 4
        elif opcode == 0xB9:  # LDA abs,Y
            self.a = self.bus.read(self.abs_y_addr())
            self.set_zn(self.a)
            used = 4
        elif opcode == 0xA1:  # LDA (zp,X)
            self.a = self.bus.read(self.indirect_x_addr())
            self.set_zn(self.a)
            used = 6
        elif opcode == 0xB1:  # LDA (zp),Y
            self.a = self.bus.read(self.indirect_y_addr())
            self.set_zn(self.a)
            used = 5

        elif opcode == 0x85:  # STA zp
            self.bus.write(self.zp_addr(), self.a)
            used = 3
        elif opcode == 0x95:  # STA zp,X
            self.bus.write(self.zp_x_addr(), self.a)
            used = 4
        elif opcode == 0x8D:  # STA abs
            self.bus.write(self.abs_addr(), self.a)
            used = 4
        elif opcode == 0x9D:  # STA abs,X
            self.bus.write(self.abs_x_addr(), self.a)
            used = 5
        elif opcode == 0x99:  # STA abs,Y
            self.bus.write(self.abs_y_addr(), self.a)
            used = 5
        elif opcode == 0x81:  # STA (zp,X)
            self.bus.write(self.indirect_x_addr(), self.a)
            used = 6
        elif opcode == 0x91:  # STA (zp),Y
            self.bus.write(self.indirect_y_addr(), self.a)
            used = 6

        # Load/store X
        elif opcode == 0xA2:  # LDX #imm
            self.x = self.fetch()
            self.set_zn(self.x)
            used = 2
        elif opcode == 0xA6:  # LDX zp
            self.x = self.bus.read(self.zp_addr())
            self.set_zn(self.x)
            used = 3
        elif opcode == 0xB6:  # LDX zp,Y
            self.x = self.bus.read(self.zp_y_addr())
            self.set_zn(self.x)
            used = 4
        elif opcode == 0xAE:  # LDX abs
            self.x = self.bus.read(self.abs_addr())
            self.set_zn(self.x)
            used = 4
        elif opcode == 0xBE:  # LDX abs,Y
            self.x = self.bus.read(self.abs_y_addr())
            self.set_zn(self.x)
            used = 4
        elif opcode == 0x86:  # STX zp
            self.bus.write(self.zp_addr(), self.x)
            used = 3
        elif opcode == 0x96:  # STX zp,Y
            self.bus.write(self.zp_y_addr(), self.x)
            used = 4
        elif opcode == 0x8E:  # STX abs
            self.bus.write(self.abs_addr(), self.x)
            used = 4

        # Load/store Y
        elif opcode == 0xA0:  # LDY #imm
            self.y = self.fetch()
            self.set_zn(self.y)
            used = 2
        elif opcode == 0xA4:  # LDY zp
            self.y = self.bus.read(self.zp_addr())
            self.set_zn(self.y)
            used = 3
        elif opcode == 0xB4:  # LDY zp,X
            self.y = self.bus.read(self.zp_x_addr())
            self.set_zn(self.y)
            used = 4
        elif opcode == 0xAC:  # LDY abs
            self.y = self.bus.read(self.abs_addr())
            self.set_zn(self.y)
            used = 4
        elif opcode == 0xBC:  # LDY abs,X
            self.y = self.bus.read(self.abs_x_addr())
            self.set_zn(self.y)
            used = 4
        elif opcode == 0x84:  # STY zp
            self.bus.write(self.zp_addr(), self.y)
            used = 3
        elif opcode == 0x94:  # STY zp,X
            self.bus.write(self.zp_x_addr(), self.y)
            used = 4
        elif opcode == 0x8C:  # STY abs
            self.bus.write(self.abs_addr(), self.y)
            used = 4

        # Transfers
        elif opcode == 0xAA:  # TAX
            self.x = self.a
            self.set_zn(self.x)
            used = 2
        elif opcode == 0xA8:  # TAY
            self.y = self.a
            self.set_zn(self.y)
            used = 2
        elif opcode == 0x8A:  # TXA
            self.a = self.x
            self.set_zn(self.a)
            used = 2
        elif opcode == 0x98:  # TYA
            self.a = self.y
            self.set_zn(self.a)
            used = 2
        elif opcode == 0xBA:  # TSX
            self.x = self.sp
            self.set_zn(self.x)
            used = 2
        elif opcode == 0x9A:  # TXS
            self.sp = self.x
            used = 2

        # Stack
        elif opcode == 0x48:  # PHA
            self.push(self.a)
            used = 3
        elif opcode == 0x68:  # PLA
            self.a = self.pop()
            self.set_zn(self.a)
            used = 4
        elif opcode == 0x08:  # PHP
            self.push(self.p | BREAK | UNUSED)
            used = 3
        elif opcode == 0x28:  # PLP
            self.p = (self.pop() & ~BREAK) | UNUSED
            used = 4

        # Arithmetic and logic
        elif opcode == 0x69:  # ADC #imm
            self.adc(self.fetch())
            used = 2
        elif opcode == 0x65:  # ADC zp
            self.adc(self.bus.read(self.zp_addr()))
            used = 3
        elif opcode == 0x6D:  # ADC abs
            self.adc(self.bus.read(self.abs_addr()))
            used = 4
        elif opcode == 0xE9:  # SBC #imm
            self.sbc(self.fetch())
            used = 2
        elif opcode == 0xE5:  # SBC zp
            self.sbc(self.bus.read(self.zp_addr()))
            used = 3
        elif opcode == 0xED:  # SBC abs
            self.sbc(self.bus.read(self.abs_addr()))
            used = 4

        elif opcode == 0x29:  # AND #imm
            self.a &= self.fetch()
            self.set_zn(self.a)
            used = 2
        elif opcode == 0x25:  # AND zp
            self.a &= self.bus.read(self.zp_addr())
            self.set_zn(self.a)
            used = 3
        elif opcode == 0x2D:  # AND abs
            self.a &= self.bus.read(self.abs_addr())
            self.set_zn(self.a)
            used = 4

        elif opcode == 0x09:  # ORA #imm
            self.a |= self.fetch()
            self.set_zn(self.a)
            used = 2
        elif opcode == 0x05:  # ORA zp
            self.a |= self.bus.read(self.zp_addr())
            self.set_zn(self.a)
            used = 3
        elif opcode == 0x0D:  # ORA abs
            self.a |= self.bus.read(self.abs_addr())
            self.set_zn(self.a)
            used = 4

        elif opcode == 0x49:  # EOR #imm
            self.a ^= self.fetch()
            self.set_zn(self.a)
            used = 2
        elif opcode == 0x45:  # EOR zp
            self.a ^= self.bus.read(self.zp_addr())
            self.set_zn(self.a)
            used = 3
        elif opcode == 0x4D:  # EOR abs
            self.a ^= self.bus.read(self.abs_addr())
            self.set_zn(self.a)
            used = 4

        elif opcode == 0x24:  # BIT zp
            self.bit(self.bus.read(self.zp_addr()))
            used = 3
        elif opcode == 0x2C:  # BIT abs
            self.bit(self.bus.read(self.abs_addr()))
            used = 4

        # Compare
        elif opcode == 0xC9:  # CMP #imm
            self.compare(self.a, self.fetch())
            used = 2
        elif opcode == 0xC5:  # CMP zp
            self.compare(self.a, self.bus.read(self.zp_addr()))
            used = 3
        elif opcode == 0xCD:  # CMP abs
            self.compare(self.a, self.bus.read(self.abs_addr()))
            used = 4
        elif opcode == 0xE0:  # CPX #imm
            self.compare(self.x, self.fetch())
            used = 2
        elif opcode == 0xC0:  # CPY #imm
            self.compare(self.y, self.fetch())
            used = 2

        # Increment/decrement registers
        elif opcode == 0xE8:  # INX
            self.x = (self.x + 1) & 0xFF
            self.set_zn(self.x)
            used = 2
        elif opcode == 0xC8:  # INY
            self.y = (self.y + 1) & 0xFF
            self.set_zn(self.y)
            used = 2
        elif opcode == 0xCA:  # DEX
            self.x = (self.x - 1) & 0xFF
            self.set_zn(self.x)
            used = 2
        elif opcode == 0x88:  # DEY
            self.y = (self.y - 1) & 0xFF
            self.set_zn(self.y)
            used = 2

        # Increment/decrement memory
        elif opcode == 0xE6:  # INC zp
            addr = self.zp_addr()
            value = (self.bus.read(addr) + 1) & 0xFF
            self.bus.write(addr, value)
            self.set_zn(value)
            used = 5
        elif opcode == 0xEE:  # INC abs
            addr = self.abs_addr()
            value = (self.bus.read(addr) + 1) & 0xFF
            self.bus.write(addr, value)
            self.set_zn(value)
            used = 6
        elif opcode == 0xC6:  # DEC zp
            addr = self.zp_addr()
            value = (self.bus.read(addr) - 1) & 0xFF
            self.bus.write(addr, value)
            self.set_zn(value)
            used = 5
        elif opcode == 0xCE:  # DEC abs
            addr = self.abs_addr()
            value = (self.bus.read(addr) - 1) & 0xFF
            self.bus.write(addr, value)
            self.set_zn(value)
            used = 6

        # Shifts/rotates accumulator and memory
        elif opcode == 0x0A:  # ASL A
            self.a = self.asl_value(self.a)
            used = 2
        elif opcode == 0x06:  # ASL zp
            addr = self.zp_addr()
            value = self.asl_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 5
        elif opcode == 0x0E:  # ASL abs
            addr = self.abs_addr()
            value = self.asl_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 6

        elif opcode == 0x4A:  # LSR A
            self.a = self.lsr_value(self.a)
            used = 2
        elif opcode == 0x46:  # LSR zp
            addr = self.zp_addr()
            value = self.lsr_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 5
        elif opcode == 0x4E:  # LSR abs
            addr = self.abs_addr()
            value = self.lsr_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 6

        elif opcode == 0x2A:  # ROL A
            self.a = self.rol_value(self.a)
            used = 2
        elif opcode == 0x26:  # ROL zp
            addr = self.zp_addr()
            value = self.rol_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 5
        elif opcode == 0x2E:  # ROL abs
            addr = self.abs_addr()
            value = self.rol_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 6

        elif opcode == 0x6A:  # ROR A
            self.a = self.ror_value(self.a)
            used = 2
        elif opcode == 0x66:  # ROR zp
            addr = self.zp_addr()
            value = self.ror_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 5
        elif opcode == 0x6E:  # ROR abs
            addr = self.abs_addr()
            value = self.ror_value(self.bus.read(addr))
            self.bus.write(addr, value)
            used = 6

        # Flag control
        elif opcode == 0x18:  # CLC
            self.set_flag(CARRY, False)
            used = 2
        elif opcode == 0x38:  # SEC
            self.set_flag(CARRY, True)
            used = 2
        elif opcode == 0x58:  # CLI
            self.set_flag(INTERRUPT_DISABLE, False)
            used = 2
        elif opcode == 0x78:  # SEI
            self.set_flag(INTERRUPT_DISABLE, True)
            used = 2
        elif opcode == 0xB8:  # CLV
            self.set_flag(OVERFLOW, False)
            used = 2
        elif opcode == 0xD8:  # CLD
            self.set_flag(DECIMAL, False)
            used = 2
        elif opcode == 0xF8:  # SED
            self.set_flag(DECIMAL, True)
            used = 2

        # Flow control
        elif opcode == 0x4C:  # JMP abs
            self.pc = self.abs_addr()
            used = 3
        elif opcode == 0x6C:  # JMP (ind)
            self.pc = self.jmp_indirect_addr()
            used = 5
        elif opcode == 0x20:  # JSR abs
            target = self.abs_addr()
            ret = (self.pc - 1) & 0xFFFF
            self.push((ret >> 8) & 0xFF)
            self.push(ret & 0xFF)
            self.pc = target
            used = 6
        elif opcode == 0x40:  # RTI
            self.p = self.pop() | UNUSED
            lo = self.pop()
            hi = self.pop()
            self.pc = (hi << 8) | lo
            used = 6
        elif opcode == 0x60:  # RTS
            lo = self.pop()
            hi = self.pop()
            self.pc = (((hi << 8) | lo) + 1) & 0xFFFF
            used = 6

        # Branches
        elif opcode == 0xD0:  # BNE
            used = self.branch(not self.get_flag(ZERO))
        elif opcode == 0xF0:  # BEQ
            used = self.branch(self.get_flag(ZERO))
        elif opcode == 0x90:  # BCC
            used = self.branch(not self.get_flag(CARRY))
        elif opcode == 0xB0:  # BCS
            used = self.branch(self.get_flag(CARRY))
        elif opcode == 0x10:  # BPL
            used = self.branch(not self.get_flag(NEGATIVE))
        elif opcode == 0x30:  # BMI
            used = self.branch(self.get_flag(NEGATIVE))
        elif opcode == 0x50:  # BVC
            used = self.branch(not self.get_flag(OVERFLOW))
        elif opcode == 0x70:  # BVS
            used = self.branch(self.get_flag(OVERFLOW))

        elif opcode == 0x00:  # BRK (stop for now)
            used = 7
            self.cycles += used
            return 0

        else:
            raise NotImplementedError(f"Opcode {opcode:#04x} not implemented")

        self.cycles += used
        return used
