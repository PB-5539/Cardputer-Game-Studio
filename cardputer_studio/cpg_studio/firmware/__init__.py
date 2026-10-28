"""Placeholder for the firmware compiler (project -> Cardputer .bin for M5 Launcher).

Parked on purpose: the plan is to decide the approach together in detail first. An earlier,
never-run attempt (freezing Python into a MicroPython build with Docker) is kept in
`firmware_parked/` at the top of the repository for reference.

The IDE calls export_firmware() from Build > Export Firmware; today it only reports that this
isn't implemented, so the menu entry and the call site are already in place.
"""
from __future__ import annotations

PLACEHOLDER_MESSAGE = (
    "Exporting a Cardputer firmware (.bin) isn't built yet.\n\n"
    "Everything else works without it: write, preview and save your game here. "
    "The compiler step will be designed separately and plugged in at this menu entry."
)


class FirmwareExportNotImplemented(NotImplementedError):
    pass


def export_firmware(project, out_path: str, board: str = "cardputer") -> str:
    """Build a launcher-ready .bin for `project`. Not implemented yet."""
    raise FirmwareExportNotImplemented(PLACEHOLDER_MESSAGE)
