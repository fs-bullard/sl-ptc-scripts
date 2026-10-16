"""Scan detector registers for a target value (default 3600).

Reads registers 0..999 and reports any whose value equals the target, or is
within a few bit flips of it when treated as a 14-bit config word.

Usage:
    python scripts/scan_registers.py --dll-dir "C:/path/to/sdk"
    python scripts/scan_registers.py --target 3600 --max-flips 2 --end 999
"""

from __future__ import annotations

import argparse
import sys

from emva1288.camera.sldevice import load_sdk

WORD_BITS = 14
WORD_MASK = (1 << WORD_BITS) - 1


def read_register(sdk, device, addr: int) -> int | None:
    """Read one register, or None if the read failed.

    The wrapper returns either a bare value or an (SLError, value) tuple
    depending on the method, so accept both.
    """
    try:
        result = device.RegisterRead(addr)
    except Exception as exc:
        print(f"  register {addr}: read raised {exc}", file=sys.stderr)
        return None

    if isinstance(result, tuple):
        err, value = result
        if err != sdk.SLError.SL_ERROR_SUCCESS:
            print(f"  register {addr}: {err}", file=sys.stderr)
            return None
        return int(value)
    return int(result)


def bit_flips(a: int, b: int) -> int:
    """Hamming distance between two values in the 14-bit config word."""
    return bin((a ^ b) & WORD_MASK).count("1")


def scan(sdk, device, start: int, end: int, target: int, max_flips: int):
    """Return (addr, value, flips) for every register near the target."""
    matches = []
    for addr in range(start, end + 1):
        value = read_register(sdk, device, addr)
        if value is None:
            continue
        flips = bit_flips(value, target)
        # Bits above the 14-bit word are ignored by the comparison, so a value
        # with them set would otherwise look like an exact match.
        if value & ~WORD_MASK:
            continue
        if flips <= max_flips:
            matches.append((addr, value, flips))
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dll-dir", help="folder holding SLDevicePythonWrapper.pyd")
    parser.add_argument("--interface", default="USB", help="DeviceInterface member")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--end", type=int, default=999)
    parser.add_argument("--target", type=int, default=3600)
    parser.add_argument("--max-flips", type=int, default=2,
                        help="report values this many bits or fewer from target")
    args = parser.parse_args(argv)

    sdk = load_sdk(args.dll_dir)
    device = sdk.SLDevice(getattr(sdk.DeviceInterface, args.interface))

    err = device.OpenCamera(10)
    if err != sdk.SLError.SL_ERROR_SUCCESS:
        print(f"Failed to open camera: {err}", file=sys.stderr)
        return 1

    try:
        matches = scan(sdk, device, args.start, args.end, args.target, args.max_flips)
    finally:
        device.CloseCamera()

    print(f"Registers {args.start}-{args.end} within {args.max_flips} bit flips "
          f"of {args.target} (0x{args.target:04X}, {WORD_BITS}-bit):")
    if not matches:
        print("  none")
    for addr, value, flips in sorted(matches, key=lambda m: (m[2], m[0])):
        label = "exact" if flips == 0 else f"{flips} flip{'s' if flips > 1 else ''}"
        print(f"  reg {addr:4d}: {value:5d}  0x{value:04X}  "
              f"0b{value:0{WORD_BITS}b}  ({label})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
