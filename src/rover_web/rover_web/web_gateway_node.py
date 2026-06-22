#!/usr/bin/env python3
"""Minimal LAN-accessible web server for the rover."""

from __future__ import annotations

import json
import mimetypes
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.node import Node


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


class RoverWebGateway(Node):
    def __init__(self) -> None:
        super().__init__("web_gateway_node")

        share = Path(get_package_share_directory("rover_web"))
        self.declare_parameter("bind_address", "0.0.0.0")
        self.declare_parameter("port", 8765)
        self.declare_parameter("web_root", str(share / "web"))

        self.bind_address = str(self.get_parameter("bind_address").value)
        self.port = int(self.get_parameter("port").value)
        self.web_root = Path(
            str(self.get_parameter("web_root").value)
        ).expanduser().resolve()
        self.started_at = time.time()

        handler = self._build_handler()
        self._http_server = ThreadingHTTPServer((self.bind_address, self.port), handler)
        self._http_server.daemon_threads = True
        self._http_server.gateway = self  # type: ignore[attr-defined]
        self._http_thread = threading.Thread(
            target=self._http_server.serve_forever,
            name="rover-web-http",
            daemon=True,
        )
        self._http_thread.start()

        addresses = current_ipv4_addresses()
        address_list = ", ".join(addresses) if addresses else "no IPv4 detected"
        self.get_logger().info(
            f"Rover web is serving on http://{self.bind_address}:{self.port} "
            f"(LAN addresses: {address_list})"
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "ok": True,
            "hostname": socket.gethostname(),
            "ip_addresses": current_ipv4_addresses(),
            "bind_address": self.bind_address,
            "port": self.port,
            "started_at": self.started_at,
        }

    def _build_handler(self):
        gateway = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "RoverHello/0.1"

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/api/health":
                    self._serve_json(gateway._identity_payload(), HTTPStatus.OK)
                    return
                if self.path == "/api/identity":
                    self._serve_json(gateway._identity_payload(), HTTPStatus.OK)
                    return
                self._serve_static()

            def _serve_json(self, payload: dict[str, object], status: HTTPStatus) -> None:
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _serve_static(self) -> None:
                request_path = self.path.split("?", 1)[0]
                relative_path = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
                candidate = os.path.normpath(os.path.join(str(gateway.web_root), relative_path))
                if os.path.commonpath([str(gateway.web_root), candidate]) != str(gateway.web_root):
                    self.send_error(HTTPStatus.FORBIDDEN, "Forbidden")
                    return
                path = Path(candidate)
                if not path.exists() or not path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                    return

                content_type, _ = mimetypes.guess_type(str(path))
                payload = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header(
                    "Content-Type",
                    content_type or "application/octet-stream",
                )
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format: str, *args) -> None:
                return

        return Handler

    def destroy_node(self) -> bool:
        self._http_server.shutdown()
        self._http_server.server_close()
        self._http_thread.join(timeout=1.0)
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
        rclpy.shutdown()


if __name__ == "__main__":
    main()
