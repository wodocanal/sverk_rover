# ESP32-S3 Audio Serial STT Bridge

Firmware for the Waveshare `ESP32-S3-AUDIO-Board` used by the
`rover_waveshare_audio` ROS 2 package.

For the complete flashing and rover runtime guide, see:

```text
src/peripherals/rover_waveshare_audio/README.md
```

## What This Firmware Does

- Captures microphone audio from the Waveshare ESP32-S3 audio board.
- Mixes the microphone channels to `16 kHz mono s16le`.
- Sends framed `PCM1` packets over USB Serial/JTAG.
- Receives framed `SPK1` playback packets from the host.
- Plays received speech through the board speaker.
- Streams only while the center user button is held, plus about 2 seconds
  after release.
- Shows basic state on the RGB LED ring.

The ROS node expects this streaming firmware. The sibling
`speech-command-test` firmware is only a standalone ESP-SR demo.

## Flash

From a source workspace on Ubuntu:

```bash
cd ~/sverk_rover
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh
```

From a source workspace on macOS:

```bash
cd ~/sverk_rover
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_macos.sh
```

From Windows PowerShell:

```powershell
cd C:\path\to\sverk_rover
src\peripherals\rover_waveshare_audio\tools\flash_waveshare_audio_windows.ps1
```

From an installed ROS workspace:

```bash
cd ~/sverk_rover/install/rover_waveshare_audio/share/rover_waveshare_audio
tools/flash_waveshare_audio_ubuntu.sh
```

Inspect ports:

```bash
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh --list
```

Force a port:

```bash
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_ubuntu.sh --port /dev/ttyACM0
src/peripherals/rover_waveshare_audio/tools/flash_waveshare_audio_macos.sh --port /dev/cu.usbmodem101
```

```powershell
src\peripherals\rover_waveshare_audio\tools\flash_waveshare_audio_windows.ps1 --port COM5
```

Useful options:

```bash
--dry-run
--erase
--monitor
--no-clean
--clean-only
--allow-any-single-port
```

After successful flashing the helper removes generated ESP-IDF artifacts:

```text
build/
managed_components/
sdkconfig.old
**/__pycache__/
```

It keeps `sdkconfig` and `dependencies.lock`.

The legacy local command still works:

```bash
./flash.sh
```

## Quick Non-ROS Test

Run live transcription directly from this firmware directory:

```bash
./host/run_transcriber.sh --language ru --model tiny
```

Run a simple speech-to-speech test:

```bash
./host/run_voice_agent.sh --language ru --model tiny
```

Useful host options:

```bash
./host/run_transcriber.sh --list-models
./host/run_transcriber.sh --language ru --save-wavs-dir utterances
./host/run_voice_agent.sh --speak-text "Привет, проверка динамика"
```

## Push-To-Talk

Hold the center user button on the board to speak. After release, the firmware
keeps streaming briefly so the phrase ending is captured.

Expected visible behavior:

```text
white LED           idle
blinking green LED  listening
volume buttons      speaker volume up/down
```
