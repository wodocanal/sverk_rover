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
            'Supports multiple backends to help isolate Raspberry Pi 5 LED issues.'
        )
    )
    parser.add_argument(
        '--backend',
        choices=['auto', 'rpi_ws281x', 'adafruit_pi5'],
        default='auto',
        help='Driver backend to use (default: auto)',
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
    parser.add_argument(
        '--frequency',
        type=int,
        default=800000,
        help='Signal frequency for rpi_ws281x backend (default: 800000)',
    )
    parser.add_argument(
        '--dma',
        type=int,
        default=10,
        help='DMA channel for rpi_ws281x backend (default: 10)',
    )
    parser.add_argument(
        '--channel',
        type=int,
        default=0,
        help='PWM/PCM channel for rpi_ws281x backend (default: 0)',
    )
    parser.add_argument(
        '--invert',
        action='store_true',
        help='Use inverted output for rpi_ws281x backend',
    )
    return parser.parse_args()


def validate_pixel_order(value: str) -> str:
    text = str(value).strip().upper()
    if len(text) != 3 or set(text) != {'R', 'G', 'B'}:
        raise ValueError('pixel order must be a permutation of RGB, for example GRB')
    return text


def build_adafruit_pixels(pin_number: int, led_count: int, pixel_order: str):
    try:
        import adafruit_pixelbuf
        import board
        from adafruit_raspberry_pi5_neopixel_write import neopixel_write
    except ImportError as exc:
        raise RuntimeError(
            'Adafruit Pi 5 NeoPixel backend is not installed. Run:\n'
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

    pixels = Pi5PixelBuf(pin, led_count, byteorder=pixel_order)

    class AdafruitController:
        backend_name = 'adafruit_pi5'

        def on(self) -> None:
            pixels.brightness = 1.0
            pixels.fill((255, 255, 255))
            pixels.show()

        def off(self) -> None:
            pixels.fill((0, 0, 0))
            pixels.show()

    return AdafruitController()


def build_rpi_ws281x_pixels(
    pin_number: int,
    led_count: int,
    pixel_order: str,
    *,
    frequency: int,
    dma: int,
    channel: int,
    invert: bool,
):
    try:
        from rpi_ws281x import Color, PixelStrip, ws
    except ImportError as exc:
        raise RuntimeError(
            'rpi_ws281x backend is not installed. Run:\n'
            'python3 -m pip install rpi_ws281x'
        ) from exc

    strip_type_name = f'WS2811_STRIP_{pixel_order}'
    strip_type = getattr(ws, strip_type_name, None)
    if strip_type is None:
        raise RuntimeError(
            f'Unsupported pixel order for rpi_ws281x: {pixel_order}'
        )

    strip = PixelStrip(
        led_count,
        pin_number,
        frequency,
        dma,
        invert,
        255,
        channel,
        strip_type,
    )
    try:
        strip.begin()
    except Exception as exc:
        raise RuntimeError(
            'rpi_ws281x failed to initialize. On Raspberry Pi 5 this may require '
            'extra rp1 kernel/overlay setup and often root privileges. '
            f'Original error: {exc}'
        ) from exc

    class Ws281xController:
        backend_name = 'rpi_ws281x'

        def on(self) -> None:
            white = Color(255, 255, 255)
            for index in range(strip.numPixels()):
                strip.setPixelColor(index, white)
            strip.show()

        def off(self) -> None:
            black = Color(0, 0, 0)
            for index in range(strip.numPixels()):
                strip.setPixelColor(index, black)
            strip.show()

    return Ws281xController()


def build_controller(args: argparse.Namespace):
    pixel_order = validate_pixel_order(args.pixel_order)
    errors: list[str] = []

    backends = (
        ['rpi_ws281x', 'adafruit_pi5']
        if args.backend == 'auto'
        else [args.backend]
    )

    for backend in backends:
        try:
            if backend == 'rpi_ws281x':
                controller = build_rpi_ws281x_pixels(
                    args.pin,
                    args.count,
                    pixel_order,
                    frequency=args.frequency,
                    dma=args.dma,
                    channel=args.channel,
                    invert=args.invert,
                )
            else:
                controller = build_adafruit_pixels(
                    args.pin,
                    args.count,
                    pixel_order,
                )
            return controller
        except Exception as exc:
            errors.append(f'{backend}: {exc}')

    raise RuntimeError('No LED backend could be initialized:\n- ' + '\n- '.join(errors))


def main() -> int:
    args = parse_args()
    if args.count < 1:
        print('LED count must be >= 1', file=sys.stderr)
        return 2

    try:
        controller = build_controller(args)
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
        f'Started LED blink test using {controller.backend_name} on GPIO {args.pin} '
        f'with {args.count} LEDs, white at full brightness.'
    )

    try:
        while running:
            controller.on()
            time.sleep(max(0.01, float(args.on_sec)))
            controller.off()
            time.sleep(max(0.01, float(args.off_sec)))
    finally:
        try:
            controller.off()
        except Exception:
            pass

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
