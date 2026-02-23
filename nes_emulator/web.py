from __future__ import annotations

import argparse
import base64
import json
import struct
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import Bus, CPU, Cartridge


INDEX_HTML = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>NES Emulator (CPU Core)</title>
    <style>
      body { font-family: sans-serif; max-width: 980px; margin: 2rem auto; padding: 0 1rem; }
      .card { border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
      pre { background: #111; color: #0f0; padding: 1rem; border-radius: 6px; overflow: auto; max-height: 260px; }
      button { padding: .6rem 1rem; }
      table td { padding: .25rem .75rem .25rem 0; }
      #screen { width: 512px; image-rendering: pixelated; border: 2px solid #333; }
    </style>
  </head>
  <body>
    <h1>NES Emulator Web Runner</h1>
    <p>Upload a ROM and run it. A rendered frame will appear below.</p>

    <div class=\"card\">
      <input id=\"rom\" type=\"file\" accept=\".nes\" />
      <label for=\"max\">Max steps:</label>
      <input id=\"max\" type=\"number\" value=\"200000\" min=\"1\" />
      <label><input id=\"trace\" type=\"checkbox\" /> Include trace</label>
      <button id=\"run\">Run ROM</button>
      <p id=\"status\"></p>
    </div>

    <div class=\"card\">
      <h3>Screen</h3>
      <img id=\"screen\" alt=\"NES frame\" />
    </div>

    <div class=\"card\">
      <h3>CPU state</h3>
      <table id=\"regs\"></table>
    </div>

    <div class=\"card\">
      <h3>Trace</h3>
      <pre id=\"traceOut\"></pre>
    </div>

    <script>
      const statusEl = document.getElementById('status');
      const regsEl = document.getElementById('regs');
      const traceEl = document.getElementById('traceOut');
      const screenEl = document.getElementById('screen');

      function setRegs(state) {
        regsEl.innerHTML = '';
        Object.entries(state).forEach(([k, v]) => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td><strong>${k}</strong></td><td>${v}</td>`;
          regsEl.appendChild(tr);
        });
      }

      document.getElementById('run').addEventListener('click', async () => {
        const fileInput = document.getElementById('rom');
        const file = fileInput.files[0];
        if (!file) {
          statusEl.textContent = 'Select a ROM first.';
          return;
        }
        statusEl.textContent = 'Reading ROM...';
        const bytes = Array.from(new Uint8Array(await file.arrayBuffer()));
        const payload = {
          rom: bytes,
          max_steps: Number(document.getElementById('max').value || 200000),
          trace: document.getElementById('trace').checked,
        };

        statusEl.textContent = 'Running...';
        traceEl.textContent = '';
        const res = await fetch('/api/run', {
          method: 'POST',
          headers: {'content-type': 'application/json'},
          body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (!res.ok) {
          statusEl.textContent = `Error: ${data.error || 'unknown error'}`;
          return;
        }

        statusEl.textContent = `Done. ${data.termination} after ${data.steps} steps.`;
        setRegs(data.cpu_state);
        traceEl.textContent = (data.trace || []).join('\n');
        screenEl.src = `data:image/bmp;base64,${data.frame_bmp_base64}`;
      });
    </script>
  </body>
</html>
"""


@dataclass
class RunResult:
    termination: str
    steps: int
    cpu_state: dict[str, int]
    trace: list[str]
    frame_bmp_base64: str


def rgb_to_bmp_base64(width: int, height: int, rgb: bytes) -> str:
    row_stride = (width * 3 + 3) & ~3
    pixel_data_size = row_stride * height
    file_size = 14 + 40 + pixel_data_size

    file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 14 + 40)
    dib_header = struct.pack(
        "<IIIHHIIIIII",
        40,
        width,
        height,
        1,
        24,
        0,
        pixel_data_size,
        2835,
        2835,
        0,
        0,
    )

    out = bytearray()
    for y in range(height - 1, -1, -1):
        row = bytearray()
        base = y * width * 3
        for x in range(width):
            i = base + x * 3
            r, g, b = rgb[i], rgb[i + 1], rgb[i + 2]
            row.extend((b, g, r))
        row.extend(b"\x00" * (row_stride - width * 3))
        out.extend(row)

    bmp = file_header + dib_header + bytes(out)
    return base64.b64encode(bmp).decode("ascii")


def run_rom_bytes(rom: bytes, max_steps: int = 200000, include_trace: bool = False) -> RunResult:
    cart = Cartridge.from_bytes(rom)
    bus = Bus(cart)
    cpu = CPU(bus)
    cpu.reset()

    steps = 0
    trace: list[str] = []
    termination = "step budget exhausted"
    while steps < max_steps:
        pc_before = cpu.pc
        opcode = bus.read(pc_before)
        used = cpu.step()
        if used:
            bus.tick(used)
        if include_trace:
            trace.append(
                f"PC={pc_before:04X} OP={opcode:02X} A={cpu.a:02X} X={cpu.x:02X} "
                f"Y={cpu.y:02X} P={cpu.p:02X} SP={cpu.sp:02X} CYC={cpu.cycles}"
            )
        steps += 1
        if used == 0:
            termination = "program terminated by BRK"
            break

    frame = bus.ppu.render_frame_rgb()
    frame_b64 = rgb_to_bmp_base64(256, 240, frame)

    return RunResult(
        termination=termination,
        steps=steps,
        cpu_state={"A": cpu.a, "X": cpu.x, "Y": cpu.y, "P": cpu.p, "SP": cpu.sp, "PC": cpu.pc, "cycles": cpu.cycles},
        trace=trace,
        frame_bmp_base64=frame_b64,
    )


class EmulatorWebHandler(BaseHTTPRequestHandler):
    def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = INDEX_HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8"))
            rom = bytes(payload["rom"])
            max_steps = int(payload.get("max_steps", 200000))
            include_trace = bool(payload.get("trace", False))
            result = run_rom_bytes(rom=rom, max_steps=max_steps, include_trace=include_trace)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._json(
            {
                "termination": result.termination,
                "steps": result.steps,
                "cpu_state": result.cpu_state,
                "trace": result.trace,
                "frame_bmp_base64": result.frame_bmp_base64,
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the emulator web UI")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), EmulatorWebHandler)
    print(f"NES emulator web UI on http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
