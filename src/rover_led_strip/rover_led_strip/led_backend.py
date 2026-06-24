from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class BackendUnavailableError(RuntimeError):
    """Raised when the Pi 5 NeoPixel backend cannot be created."""


@dataclass
class BackendInfo:
    name: str
    connected: bool
    status_message: str


class LedStripBackend:
    """Thin wrapper around the Pi 5 NeoPixel write backend."""

    def __init__(self, gpio_pin: int, led_count: int, pixel_order: str) -> None:
        try:
            import adafruit_pixelbuf
            import board
            from adafruit_raspberry_pi5_neopixel_write import neopixel_write
        except ImportError as exc:  # pragma: no cover - hardware-specific import
            raise BackendUnavailableError(
                'Pi 5 NeoPixel Python stack is not installed. '
                'Install Adafruit-Blinka, adafruit-circuitpython-pixelbuf and '
                'Adafruit-Blinka-Raspberry-Pi5-Neopixel.'
            ) from exc

        pin_name = f'D{int(gpio_pin)}'
        pin = getattr(board, pin_name, None)
        if pin is None:
            raise BackendUnavailableError(
                f'board.{pin_name} is not available in the current Blinka setup.'
            )

        class Pi5PixelBuf(adafruit_pixelbuf.PixelBuf):
            def __init__(self, physical_pin, size, *, byteorder: str) -> None:
                self._pin = physical_pin
                super().__init__(
                    size=size,
                    auto_write=False,
                    byteorder=byteorder,
                )

            def _transmit(self, buf: bytes) -> None:
                neopixel_write(self._pin, buf)

        self._pixels = Pi5PixelBuf(pin, int(led_count), byteorder=str(pixel_order))
        self.info = BackendInfo(
            name='adafruit-pi5-pio',
            connected=True,
            status_message='LED strip backend is ready.',
        )

    def show(
        self,
        colors: Iterable[tuple[int, int, int]],
        *,
        brightness: float,
    ) -> None:
        self._pixels.brightness = max(0.0, min(1.0, float(brightness)))
        for index, color in enumerate(colors):
            self._pixels[index] = tuple(int(channel) for channel in color[:3])
        self._pixels.show()

    def clear(self) -> None:
        self._pixels.fill((0, 0, 0))
        self._pixels.show()
