from rover_base_driver.motor_calibration import (MotorCalibration, calibration_from_observations,
                                                load_calibration)
import pytest


class FakeProtocol:
    command_order = feedback_order = (0, 1, 2, 3)
    command_signs = feedback_signs = (1, 1, 1, 1)

    def __init__(self):
        self.now = 0.0
        self.counts = [0]*4
        self.sample_time = 0.0
        self.commands = []

    def hold_stop(self): self.commands.append('hold')
    def release(self): self.commands.append('release')
    def calibration_speed(self, channel, speed): self.commands.append((channel, speed))
    def raw_counts(self): return (tuple(self.counts), self.sample_time)


def test_mapping_uses_inverse_permutation_for_encoders():
    values = calibration_from_observations([
        dict(wheel=2, direction=-1, encoder_channel=0, encoder_sign=-1),
        dict(wheel=0, direction=1, encoder_channel=1, encoder_sign=1),
        dict(wheel=3, direction=-1, encoder_channel=2, encoder_sign=1),
        dict(wheel=1, direction=1, encoder_channel=3, encoder_sign=-1),
    ])
    assert values['motor_command_order'] == [2, 0, 3, 1]
    assert values['motor_command_signs'] == [-1, 1, -1, 1]
    assert values['encoder_feedback_order'] == [1, 3, 0, 2]
    assert values['encoder_feedback_signs'] == [1, -1, 1, -1]


def test_full_wizard_pulses_stop_and_persist_only_after_save(tmp_path):
    protocol = FakeProtocol()
    path = tmp_path/'calibration.json'
    session = MotorCalibration(protocol, str(path), clock=lambda: protocol.now)
    with pytest.raises(ValueError): session.command('begin')
    session.command('begin', True)
    for channel in range(4):
        session.command('pulse')
        assert protocol.commands[-1] == (channel, 60)
        with pytest.raises(ValueError): session.command('record', wheel=channel, direction=1)
        protocol.now += 2.01
        protocol.sample_time = protocol.now
        protocol.counts[channel] += 20
        session.tick()
        assert protocol.commands[-1] == 'release'
        assert not session.pulsing
        assert session.active
        assert not path.exists()
        session.command('record', wheel=channel, direction=1)
    session.command('save')
    assert load_calibration(path)['motor_command_order'] == [0, 1, 2, 3]
    assert session.active  # Saving must not silently re-enable normal motion.
    session.command('end')
    assert not session.active


def test_stale_feedback_aborts_and_cannot_be_recorded(tmp_path):
    protocol = FakeProtocol()
    session = MotorCalibration(protocol, str(tmp_path/'config'), clock=lambda: protocol.now)
    session.command('begin', True)
    session.command('pulse')
    protocol.now = 0.5
    session.tick()
    assert not session.pulsing and session.active
    assert protocol.commands[-1] == 'release'
    with pytest.raises(ValueError): session.command('record', wheel=0, direction=1)


def test_ambiguous_feedback_and_duplicate_wheels_rejected(tmp_path):
    protocol = FakeProtocol()
    session = MotorCalibration(protocol, str(tmp_path/'config'), clock=lambda: protocol.now)
    session.command('begin', True)
    session.command('pulse')
    protocol.now = protocol.sample_time = 2.1
    protocol.counts = [20, 20, 0, 0]
    session.tick()
    assert not session.state()['can_record']
    with pytest.raises(ValueError): session.command('save')
    session.observations = [dict(wheel=0, direction=1, encoder_channel=0, encoder_sign=1)]
    session.observed_encoder = dict(encoder_channel=1, encoder_sign=1)
    with pytest.raises(ValueError): session.command('record', wheel=0, direction=1)
