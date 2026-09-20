"""ROS/HTTP maintenance test with an in-memory motor board, never real serial IO."""
import json
import threading
import time
from urllib.request import Request, urlopen

import pytest
import rclpy
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from rover_base_driver import base_driver_node as driver_module
from rover_web.web_gateway_node import RoverWebGateway


class FakeBoard:
    def __init__(self, _device, _baudrate, order, signs, feedback, feedback_signs):
        self.command_order, self.command_signs = order, signs
        self.feedback_order, self.feedback_signs = feedback, feedback_signs
        self.counts, self.commands = [0]*4, []
        self.connected = True

    def raw_counts(self): return (tuple(self.counts), time.monotonic() if self.connected else 0.0)
    def calibration_speed(self, channel, speed):
        self.counts[channel] += 2
        self.commands.append((channel, speed))
    def hold_stop(self): self.commands.append('hold')
    def release(self): self.commands.append('release')
    def sample(self): return None
    def battery(self): return None
    def request_battery(self): pass
    def close(self): self.release()


def test_http_motor_calibration_and_driver_interlock(tmp_path, monkeypatch):
    monkeypatch.setattr(driver_module, 'QuadMdProtocol', FakeBoard)
    rclpy.init(args=['--ros-args', '-p', 'port:=0',
        '-p', f'motor_calibration_file:={tmp_path}/motors.json',
        '-p', f'device_setup_config:={tmp_path}/devices.json',
        '-p', f'hackathon_files_root:={tmp_path}/files',
        '-p', f'plans_directory:={tmp_path}/plans'])
    gateway, driver = None, None
    executor = SingleThreadedExecutor()
    worker = None
    try:
        driver = driver_module.BaseDriverNode()
        gateway = RoverWebGateway()
        executor.add_node(driver)
        executor.add_node(gateway)
        worker = threading.Thread(target=executor.spin, daemon=True)
        worker.start()
        url = f'http://127.0.0.1:{gateway._http_server.server_port}'

        def command(command, **kwargs):
            data = json.dumps(dict(command=command, **kwargs)).encode()
            with urlopen(Request(url+'/api/maintenance/motors', data=data,
                                 headers={'Content-Type': 'application/json'}), timeout=5) as response:
                return json.load(response)

        for _ in range(50):
            if command('status')['available']: break
            time.sleep(0.1)
        assert command('begin', wheels_raised=True)['active']
        with pytest.raises(RuntimeError, match='Finish motor calibration'):
            gateway.set_drive_command(0.1, 0, 0)
        message = Twist()
        message.linear.x = 0.2
        driver._cmd(message)
        assert driver.target == [0.0]*3
        for wheel in range(4):
            assert command('pulse')['pulsing']
            deadline = time.monotonic()+4
            while time.monotonic() < deadline:
                status = command('status')
                if not status['pulsing']: break
                time.sleep(0.1)
            assert status['can_record']
            assert driver.protocol.commands[-1] == 'release'
            command('record', wheel=wheel, direction=1)
        assert command('save')['saved']
        assert (tmp_path/'motors.json').exists()
        assert driver.calibration.active
        assert command('end')['active'] is False
        command('begin', wheels_raised=True)
        command('pulse')
        with urlopen(Request(url+'/api/stop', data=b'{}', headers={'Content-Type': 'application/json'})) as response:
            assert response.status == 200
        assert not command('status')['pulsing']
        assert driver.calibration.active
    finally:
        executor.shutdown(timeout_sec=3)
        if worker: worker.join(timeout=3)
        if gateway: gateway.destroy_node()
        if driver:
            driver.close()
            driver.destroy_node()
        rclpy.shutdown()
