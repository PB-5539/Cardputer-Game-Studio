# Parked: first firmware attempt

Not wired into the IDE. Kept for when we come back to the firmware compiler.

- `build.py` + `docker/` : Docker build that freezes Python into a MicroPython ESP32-S3 app `.bin`
  (never run end to end - written without Docker available).
- `engine/hal_cardputer.py` : display (ST7789) + keyboard drivers, written from memory, never run on hardware.
- `engine/core.py`, `games/`, `tests/` : the earlier class-based engine API. Superseded by the
  function-style API in `cpg_studio/runtime/api.py`.
