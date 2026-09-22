from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time


DEFAULT_CALIBRATION_FILE = '~/.config/sverk-rover/motor_calibration.json'
WHEELS = ('front_left', 'front_right', 'rear_left', 'rear_right')
KEYS = ('motor_command_order', 'motor_command_signs',
        'encoder_feedback_order', 'encoder_feedback_signs')


def validate_calibration(values):
    result = {}
    for key in KEYS:
        items = values[key]
        if not isinstance(items, list) or len(items) != 4 or any(type(v) is not int for v in items):
            raise ValueError(f'Invalid calibration array: {key}')
        if key.endswith('order'):
            if sorted(items) != [0, 1, 2, 3]:
                raise ValueError(f'Invalid permutation: {key}')
        elif any(v not in (-1, 1) for v in items):
            raise ValueError(f'Invalid signs: {key}')
        result[key] = list(items)
    return result


def load_calibration(path):
    path = Path(path).expanduser()
    if not path.exists():
        return None
    return validate_calibration(json.loads(path.read_text()))


def calibration_from_observations(observations):
    if len(observations) != 4 or sorted(item['wheel'] for item in observations) != [0, 1, 2, 3]:
        raise ValueError('Observe each of the four wheels exactly once')
    order, signs, feedback, feedback_signs = [0]*4, [0]*4, [0]*4, [0]*4
    for channel, item in enumerate(observations):
        wheel, direction = item['wheel'], item['direction']
        order[channel], signs[channel] = wheel, direction
        feedback[wheel] = item['encoder_channel']
        feedback_signs[wheel] = direction * item['encoder_sign']
    return validate_calibration(dict(zip(KEYS, (order, signs, feedback, feedback_signs))))


def save_calibration(path, values):
    values = validate_calibration(values)
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.with_suffix('.json.bak').write_bytes(path.read_bytes())
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            json.dump(values, output, indent=2)
            output.write('\n')
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class MotorCalibration:
    """Bounded raw-channel pulses; called only from the driver's ROS executor."""

    def __init__(self, protocol, path, clock=time.monotonic):
        self.protocol, self.path, self.clock = protocol, path, clock
        self.active = False
        self.pulsing = False
        self.observations = []
        self.observed_encoder = None
        self.deadline = 0.0
        self.message = ''
        self.saved = False

    def state(self):
        return dict(active=self.active, pulsing=self.pulsing, channel=len(self.observations),
                    observations=self.observations, can_record=self.observed_encoder is not None,
                    complete=len(self.observations) == 4, saved=self.saved,
                    message=self.message, file=str(Path(self.path).expanduser()),
                    seconds_remaining=max(0, self.deadline-self.clock()) if self.pulsing else 0,
                    effective=dict(zip(KEYS, (list(self.protocol.command_order),
                        list(self.protocol.command_signs), list(self.protocol.feedback_order),
                        list(self.protocol.feedback_signs)))))

    def stop(self, message='Test stopped'):
        self.pulsing = False
        self.observed_encoder = None
        self.message = message
        try:
            self.protocol.hold_stop()
        finally:
            self.protocol.release()

    def command(self, command, wheels_raised=False, wheel=0, direction=0):
        self.tick()
        if command == 'status':
            return self.state()
        if command == 'stop':
            self.stop()
        elif command == 'begin':
            if self.active:
                raise ValueError('Calibration is already active; finish it first')
            if not wheels_raised:
                raise ValueError('Raise all wheels and confirm before starting')
            self.stop()
            self.active, self.saved = True, False
            self.observations = []
            self.message = 'Ready: test channel 1'
        elif command == 'end':
            self.stop()
            self.active = False
        elif not self.active:
            raise ValueError('Start calibration first')
        elif command == 'pulse':
            if self.pulsing or len(self.observations) == 4:
                raise ValueError('Test is running or all channels have been recorded')
            sample = self.protocol.raw_counts()
            if sample is None or self.clock()-sample[1] > 0.35:
                raise ValueError('Fresh encoder feedback is required')
            self.baseline = sample[0]
            self.observed_encoder = None
            self.deadline = self.clock()+2.0
            self.pulsing = True
            self.message = 'Testing one channel for at most 2 seconds'
            self.tick()
        elif command == 'record':
            if self.pulsing or self.observed_encoder is None:
                raise ValueError('Wait for a successful motor test first')
            if type(wheel) is not int or wheel not in range(4) or direction not in (-1, 1):
                raise ValueError('Choose a wheel and forward/backward direction')
            if any(item['wheel'] == wheel for item in self.observations):
                raise ValueError('This wheel was already assigned to another channel')
            self.observations.append(dict(wheel=wheel, direction=direction, **self.observed_encoder))
            self.observed_encoder = None
            self.message = 'Observation recorded'
        elif command == 'save':
            values = calibration_from_observations(self.observations)
            save_calibration(self.path, values)
            self.saved = True
            self.message = 'Saved. Restart rover-bringup to apply motor and encoder mapping together.'
        else:
            raise ValueError('Unknown calibration command')
        return self.state()

    def tick(self):
        if not self.pulsing:
            return
        sample = self.protocol.raw_counts()
        if sample is None or self.clock()-sample[1] > 0.35:
            self.stop('Encoder feedback lost; test aborted')
            return
        if self.clock() >= self.deadline:
            self.stop('Test complete; choose the wheel and direction')
            deltas = [a-b for a, b in zip(sample[0], self.baseline)]
            channel = max(range(4), key=lambda i: abs(deltas[i]))
            if abs(deltas[channel]) < 3 or any(abs(delta) > max(2, abs(deltas[channel])*0.2)
                                                for i, delta in enumerate(deltas) if i != channel):
                self.message = 'No clear single encoder movement; check wiring and repeat'
                return
            if any(item['encoder_channel'] == channel for item in self.observations):
                self.message = 'Encoder channel was already used; check wiring'
                return
            self.observed_encoder = dict(encoder_channel=channel, encoder_sign=1 if deltas[channel] > 0 else -1)
        else:
            self.protocol.calibration_speed(len(self.observations), 60)
