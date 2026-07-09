# rover_voice

ROS 2 driver for the Yahboom ASR/TTS voice interaction module.

The package uses the module UART protocol observed on the rover:

- received command frame: `AA 55 <frame_type> <command_id> FB`
- passive broadcast frame: `AA FF FF <phrase_id> FB`
- default serial speed: `115200`

The default config expects the module at `/dev/myspeech`. Yahboom examples use
the CH340 USB serial adapter id `1a86:7522`; copy the bundled udev rule to keep
that stable device name.

## Topics

- Publishes `rover_interfaces/msg/VoiceCommand` on `/voice/command`.
- Publishes command IDs as `std_msgs/msg/UInt8` on `/voice/command_id`.
- Publishes raw frames as hex strings on `/voice/raw_frame`.
- Publishes every received serial chunk as hex strings on `/voice/raw_bytes`.
- Subscribes to `std_msgs/msg/UInt8` on `/voice/speak_id` to play a passive
  broadcast phrase.
- Subscribes to `std_msgs/msg/String` on `/voice/speak_label` for labels from
  `phrase_labels`.

`command_labels` accepts either `id:label` or `type:id:label`. Use the second
form for frames where the command id repeats under different frame types, for
example `6:0:some_command`.

## Service

- `/voice/speak_phrase` (`rover_interfaces/srv/SpeakVoicePhrase`) plays a
  passive broadcast phrase by `phrase_id` or configured `label`.

## Run

```bash
ros2 launch rover_voice voice.launch.py
```

From `rover_bringup`:

```bash
ros2 launch rover_bringup peripherals.launch.py use_voice:=true
ros2 launch rover_bringup robot.launch.py use_voice:=true
```

## Udev

```bash
sudo cp install/rover_voice/share/rover_voice/udev/99-rover-voice.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```
