#!/usr/bin/env python3
from __future__ import annotations

import argparse
import signal
import sys
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Blink an addressable LED strip in white at full brightness. '
            'Designed for Raspberry Pi 5 with the Adafruit Pi 5 NeoPixel stack.'
        )
    )
    parser.add_argument(
        '--pin',
        type=int,
        default=18,
        help='BCM GPIO pin number for the LED data line (default: 18)',
    )
    parser.add_argument(
        '--count',
        type=int,
        default=16,
        help='Number of LEDs in the strip chain (default: 16)',
    )
    parser.add_argument(
        '--on-sec',
        type=float,
        default=0.5,
        help='Seconds to keep the strip on each cycle (default: 0.5)',
    )
    parser.add_argument(
        '--off-sec',
        type=float,
        default=0.5,
        help='Seconds to keep the strip off each cycle (default: 0.5)',
    )
    parser.add_argument(
        '--pixel-order',
        type=str,
        default='GRB',
        help='Pixel byte order, for example GRB or RGB (default: GRB)',
    )
    return parser.parse_args()


def validate_pixel_order(value: str) -> str:
    text = str(value).strip().upper()
    if len(text) != 3 or set(text) != {'R', 'G', 'B'}:
        raise ValueError('pixel order must be a permutation of RGB, for example GRB')
    return text


def build_pixels(pin_number: int, led_count: int, pixel_order: str):
    try:
        import adafruit_pixelbuf
        import board
        from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    except ImportError as exc:
        raise RuntimeError(
            'Required Pi 5 NeoPixel packages are not installed. Run:\n'
            'python3 -m pip install --upgrade '
            'Adafruit-Blinka adafruit-circuitpython-pixelbuf '
            'Adafruit-Blinka-Raspberry-Pi5-Neopixel'
        ) from exc

    pin_name = f'D{int(pin_number)}'
    pin = getattr(board, pin_name, None)
    if pin is None:
        raise RuntimeError(f'board.{pin_name} is not available')

    class Pi5PixelBuf(adafruit_pixelbuf.PixelBuf):
        def __init__(self, physical_pin, size: int, *, byteorder: str) -> None:
            self._pin = physical_pin
            super().__init__(size=size, auto_write=False, byteorder=byteorder)

        def _transmit(self, buf: bytes) -> None:
            neopixel_write(self._pin, buf)

    return Pi5PixelBuf(pin, led_count, byteorder=pixel_order)


def main() -> int:
    args = parse_args()
    if args.count < 1:
        print('LED count must be >= 1', file=sys.stderr)
        return 2

    try:
        pixel_order = validate_pixel_order(args.pixel_order)
        pixels = build_pixels(args.pin, args.count, pixel_order)
    except Exception as exc:
        print(f'Failed to initialize LED strip: {exc}', file=sys.stderr)
        return 1

    running = True

    def stop_handler(signum, frame) -> None:
        del signum, frame
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    print(
        f'Started LED blink test on GPIO {args.pin} with {args.count} LEDs '
        f'({pixel_order}), white at full brightness.'
    )

    try:
        pixels.brightness = 1.0
        while running:
            pixels.fill((255, 255, 255))
            pixels.show()
            time.sleep(max(0.01, float(args.on_sec)))

            pixels.fill((0, 0, 0))
            pixels.show()
            time.sleep(max(0.01, float(args.off_sec)))
    finally:
        try:
            pixels.fill((0, 0, 0))
            pixels.show()
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
