# rover_waveshare_audio

ROS 2 Whisper STT bridge for the Waveshare `ESP32-S3-AUDIO-Board`.

The ESP32 firmware streams framed `16 kHz mono s16le` PCM packets over USB
Serial/JTAG using the same `PCM1` protocol as the working `voice test`
prototype. The ROS node reads those frames, detects utterances, transcribes
them with Whisper, and publishes recognized text.

## Topics

- `/voice/text` (`std_msgs/msg/String`) recognized text.
- `/voice/transcript` (`std_msgs/msg/String`) JSON transcript metadata.
- `/waveshare_audio/status` (`std_msgs/msg/String`) connection/STT status.

All topic names are configurable in `config/waveshare_audio.yaml`.

## Firmware

The source prototypes from `voice test` are stored in `firmware/`:

- `firmware/speech-stream-stt`: recommended firmware for ROS STT.
- `firmware/speech-command-test`: local ESP-SR wake-word/command test.

Flash the streaming firmware:

```bash
cd install/rover_waveshare_audio/share/rover_waveshare_audio/firmware/speech-stream-stt
PORT=/dev/cu.usbmodem11401 ./flash.sh
```

On Raspberry Pi the port is usually `/dev/ttyACM0`.

## Host Dependencies

Install Python dependencies on the computer that runs the ROS node:

```bash
python3 -m pip install -U openai-whisper
```

Whisper also needs PyTorch. On macOS/desktop this is usually installed by the
command above. On Raspberry Pi, install the PyTorch build that matches your OS
and Python version, then verify:

```bash
python3 - <<'PY'
import whisper
import torch
print('whisper ok')
print('torch', torch.__version__)
PY
```

## Run

Standalone:

```bash
ros2 launch rover_waveshare_audio waveshare_audio.launch.py
```

From rover bringup:

```bash
ros2 launch rover_bringup robot.launch.py use_waveshare_audio:=true
```

Example override:

```bash
ros2 launch rover_waveshare_audio waveshare_audio.launch.py \
  whisper_model:=small \
  output_topic:=/agent/text
```

## Important Parameters

- `serial_device`: serial device, default `/dev/waveshare_audio`.
- `baudrate`: streaming firmware baud rate, default `2000000`.
- `output_topic`: text output topic, default `/voice/text`.
- `whisper_model`: `tiny`, `base`, `small`, `medium`, `large`, `turbo`, etc.
- `language`: `ru`, `en`, or empty string for Whisper auto-detect.
- `device`: `auto`, `cpu`, `cuda`, `mps`.
- `min_rms`, `start_frames`, `stop_frames`: simple energy VAD tuning.

## Udev

Install the optional udev rule on Raspberry Pi:

```bash
sudo cp install/rover_waveshare_audio/share/rover_waveshare_audio/udev/99-rover-waveshare-audio.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then reconnect the board and check:

```bash
ls -l /dev/waveshare_audio
```
