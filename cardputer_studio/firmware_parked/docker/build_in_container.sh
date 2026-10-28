#!/bin/bash
# Runs inside the container: build MicroPython with /stage/manifest.py frozen in.
set -euo pipefail
BOARD="${1:-ESP32_GENERIC_S3}"

. "${IDF_PATH}/export.sh" > /dev/null
cd /mpy/ports/esp32
make BOARD="${BOARD}" FROZEN_MANIFEST=/stage/manifest.py -j"$(nproc)"

# micropython.bin is the app-only image (no bootloader/partition table), which is what
# an app launcher expects; firmware.bin would be the merged full-flash image.
cp "build-${BOARD}/micropython.bin" /out/micropython.bin
