from __future__ import annotations

from dataclasses import dataclass


BUTTON_BITS = {
    "a": 0,
    "b": 1,
    "select": 2,
    "start": 3,
    "up": 4,
    "down": 5,
    "left": 6,
    "right": 7,
}


@dataclass
class Controller:
    """NES controller serial shift register behavior for $4016/$4017 reads."""

    state: int = 0
    strobe: bool = False
    shift: int = 0

    def set_buttons(self, **buttons: bool) -> None:
        for name, pressed in buttons.items():
            if name not in BUTTON_BITS:
                raise ValueError(f"Unknown button: {name}")
            mask = 1 << BUTTON_BITS[name]
            if pressed:
                self.state |= mask
            else:
                self.state &= ~mask
        self.state &= 0xFF

    def write_strobe(self, value: int) -> None:
        self.strobe = bool(value & 1)
        if self.strobe:
            self.shift = self.state

    def read(self) -> int:
        if self.strobe:
            # While strobing, controller repeatedly returns A button.
            return self.state & 1

        value = self.shift & 1
        self.shift = ((self.shift >> 1) | 0x80) & 0xFF
        return value

    def latch(self) -> None:
        self.shift = self.state
