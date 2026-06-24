# rover_led_strip

ROS 2 package for controlling an addressable LED strip from the rover and from `rover_web`.

## Raspberry Pi 5 Python dependencies

On the rover install the Pi 5 NeoPixel stack once:

```bash
python3 -m pip install --upgrade Adafruit-Blinka adafruit-circuitpython-pixelbuf Adafruit-Blinka-Raspberry-Pi5-Neopixel
```

## Wiring note

The current config defaults to `GPIO2` because that is how the strip is connected right now.

Important: `GPIO2` is also the default I2C SDA pin on Raspberry Pi. If Octoliner or any other I2C device is connected on the same bus, driving the LED strip on `GPIO2` can conflict with I2C traffic. For stable simultaneous work, move the LED data wire to a separate GPIO and update `gpio_pin` in the config.
