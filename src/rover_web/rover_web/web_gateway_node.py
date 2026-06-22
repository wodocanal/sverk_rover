#!/usr/bin/env python3
"""Lightweight local web gateway for the Sverh rover.

The node deliberately keeps the HTTP API small. High-rate and arbitrary ROS
access is handled by rosbridge; this process supplies identity, health data,
route execution, a software stop endpoint, and static web assets.
"""

from __future__ import annotations

import json
import math
import mimetypes
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import yaml
from ament_index_python.packages import get_package_share_directory
from diagnostic_msgs.msg import DiagnosticArray
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Imu


MAX_REQUEST_BYTES = 1_000_000
PLAN_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def monotonic_age(timestamp: float) -> float | None:
    if timestamp <= 0.0:
        return None
    return max(0.0, time.monotonic() - timestamp)


def quaternion_yaw(message: Odometry) -> float:
    q = message.pose.pose.orientation
    return math.atan2(
        2.0 * (q.w * q.z + q.x * q.y),
        1.0 - 2.0 * (q.y * q.y + q.z * q.z),
    )


def read_yaml(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else fallback
    except (OSError, yaml.YAMLError):
        return fallback


def current_ipv4_addresses() -> list[str]:
    addresses: list[str] = []
    try:
        output = subprocess.run(
            ["hostname", "-I"],
            check=False,
            capture_output=True,
            text=True,
            timeout=0.5,
        ).stdout
        for candidate in output.split():
            if ":" not in candidate and not candidate.startswith("127."):
                addresses.append(candidate)
    except (OSError, subprocess.SubprocessError):
        pass
    return list(dict.fromkeys(addresses))


@dataclass
class TopicSnapshot:
    received_monotonic: float = 0.0
    message_count: int = 0


class RoverWebGateway(Node):
    def __init__(self) -> None:
        super().__init__("web_gateway_node")

        share = Path(get_package_share_directory("rover_web"))
        try:
            rover_share = Path(get_package_share_directory("rover_bringup"))
        except Exception:
            rover_share = share
        home = Path.home()

        self.declare_parameter("bind_address", "127.0.0.1")
        self.declare_parameter("port", 8765)
        self.declare_parameter("identity_file", str(share / "config" / "robot_identity.yaml"))
        self.declare_parameter("rover_config_file", str(rover_share / "config" / "rover.yaml"))
        self.declare_parameter("web_root", str(share / "web"))
        self.declare_parameter(
            "motion_executor_path",
            str(share / "tools" / "rover_motion_executor.py"),
        )
        self.declare_parameter(
            "plans_directory",
            str(home / ".local" / "share" / "sverh-rover-web" / "plans"),
        )
        self.declare_parameter("seed_plans_directory", str(share / "plans"))
        self.declare_parameter("command_topic", "/cmd_vel")
        self.declare_parameter("web_command_topic", "/web/cmd_vel")
        self.declare_parameter("web_command_timeout_sec", 0.20)
        self.declare_parameter("rosbridge_url", "")
        self.declare_parameter("rosbridge_port", 9090)
        self.declare_parameter("rosbridge_path", "/")
        self.declare_parameter("terminal_enabled", False)
        self.declare_parameter("terminal_url", "")
        self.declare_parameter("terminal_port", 7681)
        self.declare_parameter("terminal_path", "/")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("wheel_odom_topic", "/wheel/odometry")
        self.declare_parameter("imu_topic", "/imu/data")
        self.declare_parameter("diagnostics_topic", "/diagnostics")
        self.declare_parameter("runtime_dir", "/tmp/rover_devices")
        self.declare_parameter("activity_limit", 1000)
        self.declare_parameter("stop_hold_sec", 0.75)

        self.bind_address = str(self.get_parameter("bind_address").value)
        self.port = int(self.get_parameter("port").value)
        self.identity_path = Path(str(self.get_parameter("identity_file").value)).expanduser()
        self.rover_config_path = Path(str(self.get_parameter("rover_config_file").value)).expanduser()
        self.web_root = Path(str(self.get_parameter("web_root").value)).expanduser().resolve()
        self.executor_path = Path(str(self.get_parameter("motion_executor_path").value)).expanduser()
        self.plans_directory = Path(str(self.get_parameter("plans_directory").value)).expanduser()
        self.seed_plans_directory = Path(
            str(self.get_parameter("seed_plans_directory").value)
        ).expanduser()
        self.command_topic = str(self.get_parameter("command_topic").value)
        self.web_command_topic = str(self.get_parameter("web_command_topic").value)
        self.web_command_timeout_sec = max(0.10, float(self.get_parameter("web_command_timeout_sec").value))
        self.rosbridge_url = str(self.get_parameter("rosbridge_url").value).strip()
        self.rosbridge_port = int(self.get_parameter("rosbridge_port").value)
        self.rosbridge_path = str(self.get_parameter("rosbridge_path").value).strip() or "/"
        self.terminal_enabled = bool(self.get_parameter("terminal_enabled").value)
        self.terminal_url = str(self.get_parameter("terminal_url").value).strip()
        self.terminal_port = int(self.get_parameter("terminal_port").value)
        self.terminal_path = str(self.get_parameter("terminal_path").value).strip() or "/"
        self.odom_topic = str(self.get_parameter("odom_topic").value)
        self.runtime_dir = Path(str(self.get_parameter("runtime_dir").value)).expanduser()
        self.activity_limit = max(100, int(self.get_parameter("activity_limit").value))
        self.stop_hold_sec = max(0.2, float(self.get_parameter("stop_hold_sec").value))

        self.identity = read_yaml(
            self.identity_path,
            {
                "robot_id": "sverh-rover-0001",
                "hostname": socket.gethostname(),
                "company": "Сверх",
                "model": "mecanum-rover-v1",
                "software_version": "0.3.0",
            },
        )
        self.rover_config = read_yaml(self.rover_config_path, {})

        self._lock = threading.RLock()
        self._odom: Odometry | None = None
        self._wheel_odom: Odometry | None = None
        self._imu: Imu | None = None
        self._diagnostics: list[dict[str, Any]] = []
        self._topic_state = {
            "odom": TopicSnapshot(),
            "wheel_odometry": TopicSnapshot(),
            "imu": TopicSnapshot(),
            "diagnostics": TopicSnapshot(),
        }
        self._web_clients: dict[str, dict[str, Any]] = {}
        self._activity: deque[dict[str, Any]] = deque(maxlen=self.activity_limit)
        self._stop_until = 0.0
        self._latest_web_twist: Twist | None = None
        self._latest_web_twist_monotonic = 0.0
        self._web_drive_active = False
        self._motion_process: subprocess.Popen[str] | None = None
        self._motion_started_at: float | None = None
        self._motion_command: list[str] = []
        self._motion_log: deque[str] = deque(maxlen=500)
        self._motion_return_code: int | None = None

        self._cpu_last_total = 0
        self._cpu_last_idle = 0
        self._last_throttled_check = 0.0
        self._cached_throttled = "unavailable"
        self._last_ip_check = 0.0
        self._cached_ip_addresses: list[str] = []
        self._system_cache_monotonic = 0.0
        self._system_cache: dict[str, Any] = {}
        self._devices_cache_monotonic = 0.0
        self._devices_cache: dict[str, Any] = {}

        self.stop_publisher = self.create_publisher(Twist, self.command_topic, 10)
        self.create_subscription(Twist, self.web_command_topic, self._web_twist_callback, 10)
        self.create_subscription(Odometry, self.odom_topic, self._odom_callback, 20)
        self.create_subscription(
            Odometry,
            str(self.get_parameter("wheel_odom_topic").value),
            self._wheel_odom_callback,
            20,
        )
        self.create_subscription(
            Imu,
            str(self.get_parameter("imu_topic").value),
            self._imu_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(
            DiagnosticArray,
            str(self.get_parameter("diagnostics_topic").value),
            self._diagnostics_callback,
            10,
        )
        self.create_timer(0.05, self._drive_output_timer)
        self.create_timer(1.0, self._maintenance_timer)

        self.plans_directory.mkdir(parents=True, exist_ok=True)
        self._seed_default_plans()
        self._activity_dir = home / ".local" / "state" / "sverh-rover-web"
        self._activity_dir.mkdir(parents=True, exist_ok=True)
        self._activity_file = self._activity_dir / "activity.jsonl"

        handler = self._build_handler()
        self._http_server = ThreadingHTTPServer((self.bind_address, self.port), handler)
        self._http_server.daemon_threads = True
        self._http_server.gateway = self  # type: ignore[attr-defined]
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever,
            name="sverh-web-http",
            daemon=True,
        )
        self._http_thread.start()

        self.record_activity("system", "Web gateway started", {"port": self.port})
        self.get_logger().info(
            f"Sverh web gateway listening on http://{self.bind_address}:{self.port}"
        )

    def _touch_topic(self, key: str) -> None:
        state = self._topic_state[key]
        state.received_monotonic = time.monotonic()
        state.message_count += 1

    def _odom_callback(self, message: Odometry) -> None:
        with self._lock:
            self._odom = message
            self._touch_topic("odom")

    def _wheel_odom_callback(self, message: Odometry) -> None:
        with self._lock:
            self._wheel_odom = message
            self._touch_topic("wheel_odometry")

    def _imu_callback(self, message: Imu) -> None:
        with self._lock:
            self._imu = message
            self._touch_topic("imu")

    def _diagnostics_callback(self, message: DiagnosticArray) -> None:
        converted: list[dict[str, Any]] = []
        for status in message.status[:100]:
            converted.append(
                {
                    "name": status.name,
                    "hardware_id": status.hardware_id,
                    "level": (
                        int(status.level[0])
                        if isinstance(status.level, (bytes, bytearray, memoryview))
                        and len(status.level) > 0
                        else int(status.level)
                    ),
                    "message": status.message,
                    "values": {item.key: item.value for item in status.values[:40]},
                }
            )
        with self._lock:
            self._diagnostics = converted
            self._touch_topic("diagnostics")

    def _web_twist_callback(self, message: Twist) -> None:
        with self._lock:
            self._latest_web_twist = message
            self._latest_web_twist_monotonic = time.monotonic()

    def request_stop(self, source: str, details: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._stop_until = max(self._stop_until, time.monotonic() + self.stop_hold_sec)
        self.record_activity(source, "Software STOP requested", details or {})

    def _drive_output_timer(self) -> None:
        now = time.monotonic()
        with self._lock:
            stop_active = now < self._stop_until
            message = self._latest_web_twist
            fresh = (
                message is not None
                and now - self._latest_web_twist_monotonic <= self.web_command_timeout_sec
            )
            was_active = self._web_drive_active
            self._web_drive_active = fresh and not stop_active

        if stop_active:
            self.stop_publisher.publish(Twist())
        elif fresh and message is not None:
            self.stop_publisher.publish(message)
        elif was_active:
            self.stop_publisher.publish(Twist())

    def _maintenance_timer(self) -> None:
        cutoff = time.monotonic() - 10.0
        with self._lock:
            expired = [key for key, value in self._web_clients.items() if value["last_seen"] < cutoff]
            for key in expired:
                del self._web_clients[key]
            process = self._motion_process
            if process is not None:
                return_code = process.poll()
                if return_code is not None:
                    self._motion_return_code = return_code
                    self._motion_process = None
                    self.record_activity(
                        "routes",
                        "Motion process finished",
                        {"return_code": return_code},
                    )

    def register_heartbeat(self, session_id: str, page: str, client_ip: str) -> None:
        if not session_id or len(session_id) > 128:
            return
        with self._lock:
            self._web_clients[session_id] = {
                "session_id": session_id,
                "page": page[:64],
                "client_ip": client_ip,
                "last_seen": time.monotonic(),
            }

    def record_activity(self, source: str, message: str, details: dict[str, Any]) -> None:
        item = {
            "timestamp": time.time(),
            "source": source[:64],
            "message": message[:300],
            "details": details,
        }
        with self._lock:
            self._activity.append(item)
        try:
            self._rotate_activity_log()
            with self._activity_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    def _rotate_activity_log(self) -> None:
        try:
            if self._activity_file.exists() and self._activity_file.stat().st_size > 2_000_000:
                oldest = self._activity_file.with_suffix(".jsonl.3")
                if oldest.exists():
                    oldest.unlink()
                for index in (2, 1):
                    source = self._activity_file.with_suffix(f".jsonl.{index}")
                    if source.exists():
                        source.rename(self._activity_file.with_suffix(f".jsonl.{index + 1}"))
                self._activity_file.rename(self._activity_file.with_suffix(".jsonl.1"))
        except OSError:
            pass

    def identity_payload(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._last_ip_check > 10.0 or not self._cached_ip_addresses:
                self._cached_ip_addresses = current_ipv4_addresses()
                self._last_ip_check = now
            addresses = list(self._cached_ip_addresses)
        payload = dict(self.identity)
        payload["runtime_hostname"] = socket.gethostname()
        payload["ip_addresses"] = addresses
        return payload

    def _seed_default_plans(self) -> None:
        if any(self.plans_directory.glob("*.yaml")):
            return
        if not self.seed_plans_directory.is_dir():
            return
        for source in sorted(self.seed_plans_directory.glob("*.yaml")):
            target = self.plans_directory / source.name
            if target.exists():
                continue
            try:
                shutil.copy2(source, target)
            except OSError:
                continue


    def devices_payload(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._devices_cache_monotonic < 1.0 and self._devices_cache:
                return dict(self._devices_cache)
        path = self.runtime_dir / "devices.json"
        payload: dict[str, Any]
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            payload = {
                "available": isinstance(value, dict),
                "path": str(path),
                "devices": value if isinstance(value, dict) else {},
            }
        except (OSError, json.JSONDecodeError):
            payload = {"available": False, "path": str(path), "devices": {}}
        with self._lock:
            self._devices_cache = payload
            self._devices_cache_monotonic = now
        return dict(payload)

    def public_config_payload(self) -> dict[str, Any]:
        geometry = self.rover_config.get("geometry", {})
        encoders = self.rover_config.get("encoders", {})
        base = self.rover_config.get("base_driver", {})
        return {
            "command_topic": self.command_topic,
            "web_command_topic": self.web_command_topic,
            "web_command_timeout_sec": self.web_command_timeout_sec,
            "odom_topic": self.odom_topic,
            "web": {
                "rosbridge_url": self.rosbridge_url,
                "rosbridge_port": self.rosbridge_port,
                "rosbridge_path": self.rosbridge_path,
                "terminal_enabled": self.terminal_enabled,
                "terminal_url": self.terminal_url,
                "terminal_port": self.terminal_port,
                "terminal_path": self.terminal_path,
            },
            "geometry": geometry,
            "encoders": encoders,
            "limits": {
                "max_wheel_speed_mps": base.get("max_wheel_speed_mps", 0.35),
                "command_timeout_sec": base.get("command_timeout_sec", 0.5),
                "feedback_timeout_sec": base.get("feedback_timeout_sec", 0.35),
            },
            "recommended": {
                "manual_linear_speed_mps": 0.15,
                "minimum_practical_speed_mps": 0.10,
                "manual_angular_speed_radps": 0.25,
            },
        }

    def _pose_payload(self, message: Odometry | None) -> dict[str, Any] | None:
        if message is None:
            return None
        return {
            "x": float(message.pose.pose.position.x),
            "y": float(message.pose.pose.position.y),
            "yaw": quaternion_yaw(message),
            "vx": float(message.twist.twist.linear.x),
            "vy": float(message.twist.twist.linear.y),
            "wz": float(message.twist.twist.angular.z),
            "frame_id": message.header.frame_id,
            "child_frame_id": message.child_frame_id,
        }

    def _cpu_percent(self) -> float | None:
        try:
            fields = [int(value) for value in Path("/proc/stat").read_text().splitlines()[0].split()[1:]]
            idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
            total = sum(fields)
            if self._cpu_last_total == 0:
                value = None
            else:
                total_delta = total - self._cpu_last_total
                idle_delta = idle - self._cpu_last_idle
                value = None if total_delta <= 0 else 100.0 * (1.0 - idle_delta / total_delta)
            self._cpu_last_total = total
            self._cpu_last_idle = idle
            return value
        except (OSError, ValueError, IndexError):
            return None

    def _system_payload(self) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            if now - self._system_cache_monotonic < 0.8 and self._system_cache:
                return dict(self._system_cache)

        memory_total = memory_available = None
        try:
            values: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, value = line.split(":", 1)
                values[key] = int(value.strip().split()[0]) * 1024
            memory_total = values.get("MemTotal")
            memory_available = values.get("MemAvailable")
        except (OSError, ValueError, IndexError):
            pass

        temperature = None
        try:
            temperature = int(Path("/sys/class/thermal/thermal_zone0/temp").read_text().strip()) / 1000.0
        except (OSError, ValueError):
            pass

        if now - self._last_throttled_check > 5.0:
            self._last_throttled_check = now
            try:
                result = subprocess.run(
                    ["vcgencmd", "get_throttled"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=0.4,
                )
                self._cached_throttled = result.stdout.strip() or "unavailable"
            except (OSError, subprocess.SubprocessError):
                self._cached_throttled = "unavailable"

        disk = shutil.disk_usage("/")
        load = os.getloadavg()
        payload = {
            "cpu_percent": self._cpu_percent(),
            "load_1m": load[0],
            "load_5m": load[1],
            "load_15m": load[2],
            "memory_total_bytes": memory_total,
            "memory_available_bytes": memory_available,
            "temperature_c": temperature,
            "disk_total_bytes": disk.total,
            "disk_free_bytes": disk.free,
            "throttled": self._cached_throttled,
        }
        with self._lock:
            self._system_cache = payload
            self._system_cache_monotonic = now
        return dict(payload)

    def status_payload(self) -> dict[str, Any]:
        with self._lock:
            diagnostics = list(self._diagnostics)
            clients = [dict(value) for value in self._web_clients.values()]
            for client in clients:
                client.pop("last_seen", None)
            topic_state = {
                key: {
                    "age_sec": monotonic_age(value.received_monotonic),
                    "message_count": value.message_count,
                }
                for key, value in self._topic_state.items()
            }
            odom = self._pose_payload(self._odom)
            wheel_odom = self._pose_payload(self._wheel_odom)
            imu = None
            if self._imu is not None:
                imu = {
                    "angular_velocity_z": float(self._imu.angular_velocity.z),
                    "linear_acceleration_x": float(self._imu.linear_acceleration.x),
                    "linear_acceleration_y": float(self._imu.linear_acceleration.y),
                    "linear_acceleration_z": float(self._imu.linear_acceleration.z),
                    "frame_id": self._imu.header.frame_id,
                }
            motion = self.motion_status_payload_locked()

        highest_level = max((entry["level"] for entry in diagnostics), default=-1)
        return {
            "server_time": time.time(),
            "identity": self.identity_payload(),
            "topics": topic_state,
            "device_discovery": self.devices_payload(),
            "odom": odom,
            "wheel_odometry": wheel_odom,
            "imu": imu,
            "diagnostics": {
                "highest_level": highest_level,
                "items": diagnostics,
            },
            "clients": clients,
            "connected_clients": len(clients),
            "drive_clients": sum(1 for item in clients if item.get("page") == "drive"),
            "motion": motion,
            "system": self._system_payload(),
        }

    def activity_payload(self, limit: int) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 1000)
        with self._lock:
            return list(self._activity)[-limit:][::-1]

    def list_plans(self) -> list[dict[str, Any]]:
        plans: list[dict[str, Any]] = []
        for path in sorted(self.plans_directory.glob("*.yaml")):
            try:
                stat = path.stat()
                plan = read_yaml(path, {})
                steps = plan.get("steps", [])
                plans.append(
                    {
                        "name": path.name,
                        "size_bytes": stat.st_size,
                        "modified": stat.st_mtime,
                        "steps": len(steps) if isinstance(steps, list) else 0,
                    }
                )
            except OSError:
                continue
        return plans

    def read_plan(self, name: str) -> dict[str, Any]:
        path = self._safe_plan_path(name)
        if not path.exists():
            raise FileNotFoundError(name)
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("Plan must contain a YAML object")
        return value

    def save_plan(self, name: str, plan: dict[str, Any]) -> None:
        path = self._safe_plan_path(name)
        steps = plan.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("Plan requires a non-empty steps list")
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            yaml.safe_dump(plan, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        temporary.replace(path)
        self.record_activity("routes", "Plan saved", {"name": name, "steps": len(steps)})

    def _safe_plan_path(self, name: str) -> Path:
        name = unquote(name)
        if not PLAN_NAME_RE.fullmatch(name) or not name.endswith((".yaml", ".yml")):
            raise ValueError("Invalid plan name")
        path = (self.plans_directory / name).resolve()
        if path.parent != self.plans_directory.resolve():
            raise ValueError("Invalid plan path")
        return path

    def start_motion(self, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._motion_process is not None and self._motion_process.poll() is None:
                raise RuntimeError("A motion command is already running")

        if not self.executor_path.exists():
            raise FileNotFoundError(f"Motion executor not found: {self.executor_path}")

        kind = str(request.get("kind", "")).strip()
        command = [
            sys.executable,
            str(self.executor_path),
            "--odom-topic",
            self.odom_topic,
            "--cmd-vel-topic",
            self.command_topic,
        ]
        summary: dict[str, Any] = {"kind": kind}

        if kind == "plan":
            name = str(request.get("name", ""))
            path = self._safe_plan_path(name)
            if not path.exists():
                raise FileNotFoundError(name)
            command += ["run", str(path)]
            summary["name"] = name
        elif kind == "move":
            forward = float(request.get("forward", 0.0))
            left = float(request.get("left", 0.0))
            speed = float(request.get("speed", 0.15))
            if abs(forward) > 5.0 or abs(left) > 5.0:
                raise ValueError("Move distance is limited to 5 m per command")
            if not 0.10 <= speed <= 0.35:
                raise ValueError("Move speed must be between 0.10 and 0.35 m/s")
            command += ["move", "--forward", str(forward), "--left", str(left), "--speed", str(speed)]
            summary.update({"forward": forward, "left": left, "speed": speed})
        elif kind == "turn":
            degrees = float(request.get("degrees", 0.0))
            speed = float(request.get("speed", 0.25))
            tolerance = float(request.get("tolerance_deg", 3.0))
            if abs(degrees) > 720.0:
                raise ValueError("Turn is limited to 720 degrees per command")
            if not 0.10 <= speed <= 1.0:
                raise ValueError("Angular speed must be between 0.10 and 1.0 rad/s")
            if not 1.0 <= tolerance <= 15.0:
                raise ValueError("Tolerance must be between 1 and 15 degrees")
            command += ["turn", str(degrees), "--speed", str(speed), "--tolerance-deg", str(tolerance)]
            summary.update({"degrees": degrees, "speed": speed, "tolerance_deg": tolerance})
        else:
            raise ValueError("Unknown motion kind")

        environment = os.environ.copy()
        environment.setdefault("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
        process = subprocess.Popen(
            command,
            cwd=str(self.executor_path.parent.parent),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        with self._lock:
            self._motion_process = process
            self._motion_started_at = time.time()
            self._motion_command = command
            self._motion_log.clear()
            self._motion_return_code = None

        threading.Thread(
            target=self._read_motion_output,
            args=(process,),
            name="sverh-motion-output",
            daemon=True,
        ).start()
        self.record_activity("routes", "Motion process started", summary)
        return self.motion_status_payload()

    def _read_motion_output(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            cleaned = line.rstrip("\r\n")
            with self._lock:
                self._motion_log.append(cleaned)

    def stop_motion(self) -> dict[str, Any]:
        with self._lock:
            process = self._motion_process
        if process is not None and process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except ProcessLookupError:
                pass
            threading.Thread(
                target=self._ensure_motion_stopped,
                args=(process,),
                name="sverh-motion-stop",
                daemon=True,
            ).start()
        self.request_stop("routes", {"reason": "motion stop endpoint"})
        return self.motion_status_payload()

    def _ensure_motion_stopped(self, process: subprocess.Popen[str]) -> None:
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=2.0)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def motion_status_payload_locked(self) -> dict[str, Any]:
        process = self._motion_process
        running = process is not None and process.poll() is None
        return {
            "running": running,
            "pid": process.pid if running and process is not None else None,
            "started_at": self._motion_started_at,
            "return_code": self._motion_return_code,
            "command": list(self._motion_command),
            "log": list(self._motion_log)[-120:],
        }

    def motion_status_payload(self) -> dict[str, Any]:
        with self._lock:
            return self.motion_status_payload_locked()

    def _build_handler(self) -> type[BaseHTTPRequestHandler]:
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SverhRoverWeb/0.2"

            def log_message(self, format_string: str, *args: Any) -> None:
                gateway.get_logger().debug(format_string % args)

            def _json(self, payload: Any, status: int = 200) -> None:
                body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def _error(self, status: int, message: str) -> None:
                self._json({"ok": False, "error": message}, status)

            def _read_json(self) -> dict[str, Any]:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("Request body is too large")
                raw = self.rfile.read(length) if length else b"{}"
                value = json.loads(raw.decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("JSON body must be an object")
                return value

            def _client_ip(self) -> str:
                forwarded = self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                return forwarded or self.client_address[0]

            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                try:
                    if parsed.path == "/api/health":
                        self._json({"ok": True, "service": "sverh-rover-web"})
                    elif parsed.path == "/api/identity":
                        self._json(gateway.identity_payload())
                    elif parsed.path == "/api/status":
                        self._json(gateway.status_payload())
                    elif parsed.path == "/api/config":
                        self._json(gateway.public_config_payload())
                    elif parsed.path == "/api/activity":
                        query = parse_qs(parsed.query)
                        limit = int(query.get("limit", ["100"])[0])
                        self._json({"items": gateway.activity_payload(limit)})
                    elif parsed.path == "/api/plans":
                        self._json({"plans": gateway.list_plans()})
                    elif parsed.path.startswith("/api/plans/"):
                        name = parsed.path.removeprefix("/api/plans/")
                        self._json({"name": name, "plan": gateway.read_plan(name)})
                    elif parsed.path == "/api/motion/status":
                        self._json(gateway.motion_status_payload())
                    elif parsed.path.startswith("/api/"):
                        self._error(404, "Unknown API endpoint")
                    else:
                        self._serve_static(parsed.path)
                except FileNotFoundError as error:
                    self._error(404, str(error))
                except (ValueError, json.JSONDecodeError) as error:
                    self._error(400, str(error))
                except Exception as error:  # defensive API boundary
                    gateway.get_logger().error(f"GET {parsed.path} failed: {error}")
                    self._error(500, "Internal server error")

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                try:
                    request = self._read_json()
                    if parsed.path == "/api/heartbeat":
                        gateway.register_heartbeat(
                            str(request.get("session_id", "")),
                            str(request.get("page", "")),
                            self._client_ip(),
                        )
                        self._json({"ok": True})
                    elif parsed.path == "/api/activity":
                        gateway.record_activity(
                            str(request.get("source", "web")),
                            str(request.get("message", "Activity")),
                            request.get("details", {}) if isinstance(request.get("details", {}), dict) else {},
                        )
                        self._json({"ok": True})
                    elif parsed.path == "/api/stop":
                        gateway.request_stop(
                            str(request.get("source", "web")),
                            {"client_ip": self._client_ip(), **request.get("details", {})}
                            if isinstance(request.get("details", {}), dict)
                            else {"client_ip": self._client_ip()},
                        )
                        self._json({"ok": True})
                    elif parsed.path == "/api/motion/start":
                        self._json({"ok": True, "motion": gateway.start_motion(request)})
                    elif parsed.path == "/api/motion/stop":
                        self._json({"ok": True, "motion": gateway.stop_motion()})
                    elif parsed.path == "/api/plans/save":
                        name = str(request.get("name", ""))
                        plan = request.get("plan")
                        if not isinstance(plan, dict):
                            raise ValueError("plan must be an object")
                        gateway.save_plan(name, plan)
                        self._json({"ok": True})
                    else:
                        self._error(404, "Unknown API endpoint")
                except FileNotFoundError as error:
                    self._error(404, str(error))
                except (ValueError, RuntimeError, json.JSONDecodeError) as error:
                    self._error(400, str(error))
                except Exception as error:  # defensive API boundary
                    gateway.get_logger().error(f"POST {parsed.path} failed: {error}")
                    self._error(500, "Internal server error")

            def _serve_static(self, request_path: str) -> None:
                relative = "index.html" if request_path in ("", "/") else unquote(request_path.lstrip("/"))
                candidate = (gateway.web_root / relative).resolve()
                if gateway.web_root not in candidate.parents and candidate != gateway.web_root:
                    self._error(403, "Forbidden")
                    return
                if not candidate.is_file():
                    candidate = gateway.web_root / "index.html"
                if not candidate.is_file():
                    self._error(404, "Web files are not installed")
                    return
                body = candidate.read_bytes()
                content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "same-origin")
                self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self' ws: wss:; frame-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'self'")
                self.send_header("Cache-Control", "no-cache" if candidate.name == "index.html" else "public, max-age=3600")
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def destroy_node(self) -> bool:
        self.request_stop("system", {"reason": "gateway shutdown"})
        try:
            self._http_server.shutdown()
            self._http_server.server_close()
        except Exception:
            pass
        self.stop_motion()
        return super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = RoverWebGateway()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
