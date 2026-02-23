from __future__ import annotations

from dataclasses import dataclass


FRAME_IRQ_FLAG = 0x40


@dataclass
class APU:
    """Minimal APU register/timing model with frame IRQ behavior."""

    status: int = 0
    frame_counter: int = 0
    frame_irq_pending: bool = False
    cpu_cycle_counter: int = 0

    # Approximate 4-step sequence length in CPU cycles.
    frame_period_cycles: int = 29830

    def write_status(self, value: int) -> None:
        self.status = value & 0x1F

    def read_status(self) -> int:
        value = self.status
        if self.frame_irq_pending:
            value |= FRAME_IRQ_FLAG
        self.frame_irq_pending = False
        return value

    def write_frame_counter(self, value: int) -> None:
        self.frame_counter = value & 0xFF
        # Writing with IRQ inhibit clears frame IRQ flag.
        if value & 0x40:
            self.frame_irq_pending = False

    def irq_enabled(self) -> bool:
        return (self.frame_counter & 0x40) == 0

    def step(self, cpu_cycles: int) -> bool:
        self.cpu_cycle_counter += cpu_cycles
        irq = False
        while self.cpu_cycle_counter >= self.frame_period_cycles:
            self.cpu_cycle_counter -= self.frame_period_cycles
            if self.irq_enabled():
                self.frame_irq_pending = True
                irq = True
        return irq
