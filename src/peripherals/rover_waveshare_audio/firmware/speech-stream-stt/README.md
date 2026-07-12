# ESP32-S3 Audio Serial STT Bridge

This project turns the Waveshare `ESP32-S3-AUDIO-Board` into a USB serial audio front-end.

The board:

- captures microphone audio,
- mixes the two microphone channels down to `16 kHz mono s16le`,
- sends framed PCM packets over `USB Serial/JTAG`.
- only streams audio while the center user button is held, plus a `2s` grace period after release.

The Mac host script:

- reads the PCM frames,
- detects utterances using a simple energy-based VAD,
- transcribes each utterance with `Whisper`,
- prints text to `stdout`,
- can also append text to a file or forward it to a TCP socket or another serial/UART port.

## Firmware

Flash the board:

```bash
cd "/Users/urijgolysev/Documents/sniz/voice test/speech-stream-stt"
./flash.sh
```

## Host transcription

Run live transcription:

```bash
cd "/Users/urijgolysev/Documents/sniz/voice test/speech-stream-stt"
./host/run_transcriber.sh --language ru
```

Push-to-talk behavior:

- hold the center user button on the board to speak
- after release, the board keeps streaming for about `2` more seconds
- LED states: white = idle, blinking green = listening

Pick a specific Whisper model for testing:

```bash
./host/run_transcriber.sh --language ru --model tiny
./host/run_transcriber.sh --language ru --model base
./host/run_transcriber.sh --language ru --model small
./host/run_transcriber.sh --language ru --model medium
./host/run_transcriber.sh --language ru --model large
./host/run_transcriber.sh --language ru --model turbo
```

Show all supported model names:

```bash
./host/run_transcriber.sh --list-models
```

Useful options:

```bash
./host/run_transcriber.sh --language ru --append-file transcripts.txt
./host/run_transcriber.sh --language ru --jsonl-file transcripts.jsonl
./host/run_transcriber.sh --language ru --tcp 127.0.0.1:9000
./host/run_transcriber.sh --language ru --out-serial /dev/cu.usbserial-0001 --out-serial-baud 115200
./host/run_transcriber.sh --language ru --save-wavs-dir utterances
```

If the board gets another serial port:

```bash
./host/run_transcriber.sh --port /dev/cu.usbmodem11401
```
