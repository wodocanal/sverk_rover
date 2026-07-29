# rover_waveshare_audio

ROS 2 speech input and speech playback bridge for the Waveshare
`ESP32-S3-AUDIO-Board`.

The package has two parts:

- ESP32-S3 firmware that turns the board into a USB serial audio front-end.
- A ROS 2 node that receives microphone audio, runs Whisper STT, publishes
  recognized text, and can send synthesized speech back to the board speaker.

## Architecture

```text
microphones
  -> ESP32-S3 firmware
  -> USB Serial/JTAG, PCM1 frames, 16 kHz mono s16le
  -> waveshare_audio_node
  -> Whisper STT
  -> /voice/text

/voice/say service
  -> waveshare_audio_node
  -> Piper/espeak/say TTS
  -> USB Serial/JTAG, SPK1 frames, 16 kHz stereo s16le
  -> ESP32-S3 speaker output
```

The board uses push-to-talk. Hold the center user button to speak; after
release the firmware keeps streaming for about 2 seconds so the end of the
phrase is not cut off.

## Repository Layout

```text
rover_waveshare_audio/
├── config/default.example.yaml
├── firmware/
│   ├── speech-stream-stt/      # recommended firmware for ROS STT/TTS
│   └── speech-command-test/    # standalone ESP-SR command demo
├── launch/waveshare_audio.launch.py
├── tools/
│   ├── flash_waveshare_audio.py
│   ├── flash_waveshare_audio_macos.sh
│   ├── flash_waveshare_audio_ubuntu.sh
│   ├── flash_waveshare_audio_windows.ps1
│   ├── flash_waveshare_audio_windows.cmd
│   └── install_piper_ru_voice.sh
├── udev/99-rover-waveshare-audio.rules
└── rover_waveshare_audio/waveshare_audio_node.py
```

For normal rover operation the authoritative runtime config is:

```text
src/system/rover_bringup/config/components/audio.yaml
```

The package-level `config/default.example.yaml` is only a standalone example.

## Firmware Prerequisites

Install ESP-IDF on the laptop used for flashing. The wrappers expect the usual
installation paths:

```text
macOS/Linux: ~/esp/esp-idf/export.sh
Windows:     %USERPROFILE%\esp\esp-idf\export.ps1
```

Running the commands from an already configured ESP-IDF terminal also works.

Python `pyserial` is recommended for reliable serial-port detection:

```bash
python3 -m pip install -U pyserial
```

On Windows:

```powershell
python -m pip install -U pyserial
```

## Flash Firmware

Use `speech-stream-stt`; this is the firmware expected by the ROS node.

First connect only the Waveshare ESP32-S3 audio board to the flashing laptop.
Then list detected serial ports:

```bash
# macOS
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_macos.sh --list

# Ubuntu
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh --list
```

```powershell
# Windows PowerShell
src\peripherals\rover_waveshare_audio\tools\flash_waveshare_audio_windows.ps1 --list
```

The helper searches for Espressif USB Serial/JTAG `303a:1001`, which is the
usual USB identity of the ESP32-S3 board.

Flash on macOS:

```bash
cd ~/sverk_rover
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_macos.sh
```

Flash on Ubuntu:

```bash
cd ~/sverk_rover
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh
```

Flash on Windows PowerShell:

```powershell
cd C:\path\to\sverk_rover
src\peripherals\rover_waveshare_audio\tools\flash_waveshare_audio_windows.ps1
```

Flash on Windows CMD:

```bat
cd C:\path\to\sverk_rover
src\peripherals\rover_waveshare_audio\tools\flash_waveshare_audio_windows.cmd
```

If several boards or serial devices are connected, pass the port explicitly:

```bash
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_macos.sh --port /dev/cu.usbmodem101
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh --port /dev/ttyACM0
```

```powershell
src\peripherals\rover_waveshare_audio\tools\flash_waveshare_audio_windows.ps1 --port COM5
```

Useful flashing options:

```bash
--dry-run                 print selected port and idf.py command, do not flash
--erase                   erase flash before writing firmware
--monitor                 open idf.py monitor after flashing
--no-clean                keep ESP-IDF generated build files after flashing
--clean-only              remove generated ESP-IDF files without flashing
--allow-any-single-port   use the only visible serial port if USB identity is missing
```

After a successful flash the helper removes ESP-IDF generated files from the
firmware directory:

```text
build/
managed_components/
sdkconfig.old
**/__pycache__/
```

It intentionally keeps `sdkconfig` and `dependencies.lock`, because those are
part of the firmware configuration.

The old firmware-local entry point is still supported:

```bash
cd src/peripherals/rover_waveshare_audio/firmware/speech-stream-stt
./flash.sh
```

If flashing fails because the board does not enter bootloader mode, reconnect
the board while holding the BOOT button, or hold BOOT and press RESET, then run
the same command again.

## Firmware Behavior

The `speech-stream-stt` firmware:

- captures the onboard microphones;
- mixes audio to `16 kHz mono s16le`;
- sends framed `PCM1` packets over USB Serial/JTAG;
- accepts framed `SPK1` playback packets for the speaker;
- streams microphone audio only while the center user button is held, plus a
  short release grace period;
- uses the RGB LED ring for state feedback;
- uses board volume buttons for speaker volume.

The older `speech-command-test` firmware is only a standalone wake-word/command
demo and is not used by the ROS bringup.

## Raspberry Pi Runtime Prerequisites

Build the ROS workspace on the rover:

```bash
cd ~/sverk_rover
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install
source install/setup.bash
```

Install the stable udev alias:

```bash
sudo cp install/rover_waveshare_audio/share/rover_waveshare_audio/udev/99-rover-waveshare-audio.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Reconnect the module and check:

```bash
ls -l /dev/waveshare_audio
```

If the user running ROS cannot open the device, add it to `dialout` and log in
again:

```bash
sudo usermod -aG dialout "$USER"
```

Install STT/TTS runtime dependencies:

```bash
python3 -m pip install -U openai-whisper
sudo apt update
sudo apt install ffmpeg
python3 -m pip install -U piper-tts
```

Whisper also needs PyTorch. Install the PyTorch build that matches the rover OS
and Python version, then verify:

```bash
python3 - <<'PY'
import whisper
import torch
print('whisper ok')
print('torch', torch.__version__)
PY
```

If Whisper fails with `module 'coverage.types' has no attribute 'Tracer'`,
update the unrelated package used by Numba:

```bash
python3 -m pip install -U 'coverage>=7.6.1'
```

Install the recommended Russian Piper voice:

```bash
cd ~/sverk_rover
src/peripherals/rover_waveshare_audio/tools/install_piper_ru_voice.sh
```

The default voice directory is:

```text
~/sverk_rover/tts_voices
```

If Piper is not available, use `espeak-ng` as a lower-quality fallback:

```bash
sudo apt install ffmpeg espeak-ng
```

Then set `tts_engine: espeak-ng` in the audio config.

## ROS Topics And Service

Published topics:

```text
/voice/text                  std_msgs/msg/String, recognized text
/voice/transcript            std_msgs/msg/String, JSON transcript metadata
/waveshare_audio/status      std_msgs/msg/String, connection/STT/TTS status
```

Service:

```text
/voice/say                   rover_interfaces/srv/SpeakText
```

Topic names come from:

```text
src/system/rover_bringup/config/topics.yaml
```

The audio component maps them into the node at launch time.

## Run Standalone

```bash
cd ~/sverk_rover
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch rover_waveshare_audio waveshare_audio.launch.py
```

Override common parameters:

```bash
ros2 launch rover_waveshare_audio waveshare_audio.launch.py \
  serial_device:=/dev/waveshare_audio \
  whisper_model:=tiny \
  language:=ru \
  tts_engine:=piper
```

## Run Through Rover Bringup

The current rover profiles keep `waveshare_audio: false` by default. Enable it
explicitly:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full use_waveshare_audio:=true
```

Or enable it through the systemd environment:

```bash
sudo nano /etc/default/rover-bringup
```

```bash
ROVER_LAUNCH_ARGS="use_waveshare_audio:=true"
```

Restart the service:

```bash
sudo systemctl restart rover-bringup
```

Watch logs:

```bash
journalctl -u rover-bringup -f
```

## Test The Module

Check node status:

```bash
ros2 topic echo /waveshare_audio/status
```

Check speech recognition:

```bash
ros2 topic echo /voice/text
```

Hold the center user button, say a phrase, and release the button.

Check TTS playback:

```bash
ros2 service call /voice/say rover_interfaces/srv/SpeakText "{text: 'Привет, проверка динамика'}"
```

Check ROS node list:

```bash
ros2 node list | grep waveshare
```

## Optional Non-ROS Host Tests

The firmware folder also contains host scripts for direct testing without ROS:

```bash
cd ~/sverk_rover/src/peripherals/rover_waveshare_audio/firmware/speech-stream-stt
./host/run_transcriber.sh --language ru --model tiny
./host/run_voice_agent.sh --language ru --model tiny
```

These scripts are useful when debugging firmware/audio before starting the full
rover stack.

## Important Parameters

Configured in `src/system/rover_bringup/config/components/audio.yaml`:

```text
serial_device: /dev/waveshare_audio
baudrate: 2000000
output_topic: /voice/text
status_topic: /waveshare_audio/status
transcript_json_topic: /voice/transcript
whisper_model: base
language: ru
device: auto
min_rms: 350.0
start_frames: 3
stop_frames: 35
pre_roll_frames: 8
max_utterance_seconds: 12.0
enable_tts: true
tts_service_name: /voice/say
tts_engine: piper
piper_model: ru_RU-irina-medium
piper_data_dir: ~/sverk_rover/tts_voices
```

Tuning notes:

- Use `whisper_model: tiny` for faster but less accurate recognition.
- Use `whisper_model: small` or bigger for better recognition if the Raspberry
  Pi can handle it.
- Increase `min_rms` if background noise triggers false speech.
- Decrease `min_rms` if quiet speech is not detected.
- Increase `stop_frames` if phrase endings are cut off.
- Set `save_wavs_dir` to debug actual captured utterances.
- Set `save_tts_wavs_dir` to debug generated TTS audio.

## Troubleshooting

No serial port is found during flashing:

```bash
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh --list
```

Use a data USB cable, reconnect the board, try BOOT/RESET, or pass `--port`
explicitly.

`idf.py was not found`:

```bash
source ~/esp/esp-idf/export.sh
```

On Windows, run from an ESP-IDF PowerShell or make sure this exists:

```text
%USERPROFILE%\esp\esp-idf\export.ps1
```

`/dev/waveshare_audio` does not exist:

```bash
ls -l /dev/ttyACM*
udevadm info -a -n /dev/ttyACM0 | grep -m1 -E 'idVendor|idProduct'
```

If VID/PID are different from `303a:1001`, update
`udev/99-rover-waveshare-audio.rules`.

ROS node starts, but no text appears:

```bash
ros2 topic echo /waveshare_audio/status
ros2 topic echo /voice/text
```

Confirm the module has `speech-stream-stt` firmware, hold the center user
button while speaking, and try a lower `min_rms`.

TTS service exists, but no sound:

```bash
ros2 service call /voice/say rover_interfaces/srv/SpeakText "{text: 'Тест'}"
```

Check `ffmpeg`, Piper voice files, `tts_engine`, and the board volume buttons.

Whisper is too slow on the Raspberry Pi:

```yaml
whisper_model: tiny
device: cpu
```

Then restart the launch or service.

## Rebuild And Reflash Rules

Rebuild the ROS workspace after changing Python code, launch files, config
defaults, tools, or udev files:

```bash
colcon build --symlink-install
source install/setup.bash
```

Reflash the ESP32-S3 board only after changing files under:

```text
src/peripherals/rover_waveshare_audio/firmware/speech-stream-stt/
```

If ESP-IDF generated local build artifacts and you only want to clean them:

```bash
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh --clean-only
```
