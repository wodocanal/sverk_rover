#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
from typing import Iterable

import rclpy
from rclpy.node import Node


def discover_ipv4_addresses() -> list[str]:
    addresses: list[str] = []

    try:
        completed = subprocess.run(
            ['hostname', '-I'],
            check=False,
            capture_output=True,
            text=True,
            timeout=1.0,
        )
        if completed.returncode == 0:
            for token in completed.stdout.split():
                if token and '.' in token and not token.startswith('127.'):
                    if token not in addresses:
                        addresses.append(token)
    except (OSError, subprocess.SubprocessError):
        pass

    if addresses:
        return addresses

    try:
        hostname = socket.gethostname()
        for family, *_rest, sockaddr in socket.getaddrinfo(
            hostname,
            None,
            family=socket.AF_INET,
            type=socket.SOCK_STREAM,
        ):
            if family != socket.AF_INET:
                continue
            ip = sockaddr[0]
            if ip and not ip.startswith('127.') and ip not in addresses:
                addresses.append(ip)
    except socket.gaierror:
        pass

    return addresses


class RoverStatusDisplayNode(Node):
    def __init__(self) -> None:
        super().__init__('rover_status_display_node')

        self.declare_parameter('display_env', ':0')
        self.declare_parameter('xauthority_path', str(Path.home() / '.Xauthority'))
        self.declare_parameter('window_title', 'Rover Display')
        self.declare_parameter('header_text', 'ROVER')
        self.declare_parameter('footer_text', 'Touchscreen status panel')
        self.declare_parameter('full_screen', True)
        self.declare_parameter('refresh_sec', 1.0)
        self.declare_parameter('background_color', '#07141C')
        self.declare_parameter('panel_color', '#0C202B')
        self.declare_parameter('accent_color', '#16B8F3')
        self.declare_parameter('text_color', '#F4FBFF')
        self.declare_parameter('muted_text_color', '#8CB5C7')

        display_env = str(self.get_parameter('display_env').value).strip()
        xauthority_path = str(self.get_parameter('xauthority_path').value).strip()
        if display_env and not os.environ.get('DISPLAY'):
            os.environ['DISPLAY'] = display_env
        if xauthority_path and not os.environ.get('XAUTHORITY'):
            os.environ['XAUTHORITY'] = str(Path(xauthority_path).expanduser())

        try:
            import tkinter as tk
        except Exception as exc:  # pragma: no cover - platform specific
            raise RuntimeError(
                'Tkinter is not available. Install python3-tk or use a desktop image.'
            ) from exc

        self._tk = tk
        self._refresh_ms = max(
            200,
            int(float(self.get_parameter('refresh_sec').value) * 1000.0),
        )

        self._window_title = str(self.get_parameter('window_title').value)
        self._header_text = str(self.get_parameter('header_text').value)
        self._footer_text = str(self.get_parameter('footer_text').value)
        self._full_screen = bool(self.get_parameter('full_screen').value)
        self._background_color = str(self.get_parameter('background_color').value)
        self._panel_color = str(self.get_parameter('panel_color').value)
        self._accent_color = str(self.get_parameter('accent_color').value)
        self._text_color = str(self.get_parameter('text_color').value)
        self._muted_text_color = str(self.get_parameter('muted_text_color').value)

        self._root = self._create_window()
        self._hostname_var = tk.StringVar(value=socket.gethostname())
        self._ip_var = tk.StringVar(value='Поиск адреса...')
        self._status_var = tk.StringVar(value='Экран ровера активен')

        self._build_layout()
        self._update_ip_addresses()

    def _create_window(self):
        try:
            root = self._tk.Tk()
        except Exception as exc:  # pragma: no cover - platform specific
            raise RuntimeError(
                'Could not open touchscreen window. '
                'Check DISPLAY/XAUTHORITY or launch from the desktop session.'
            ) from exc

        root.title(self._window_title)
        root.configure(bg=self._background_color)
        if self._full_screen:
            root.attributes('-fullscreen', True)
        root.bind('<Escape>', lambda _event: self._shutdown())
        root.protocol('WM_DELETE_WINDOW', self._shutdown)
        return root

    def _build_layout(self) -> None:
        tk = self._tk
        root = self._root

        container = tk.Frame(root, bg=self._background_color)
        container.pack(fill='both', expand=True, padx=36, pady=28)

        header = tk.Label(
            container,
            text=self._header_text,
            bg=self._background_color,
            fg=self._accent_color,
            font=('DejaVu Sans', 32, 'bold'),
            anchor='center',
        )
        header.pack(fill='x', pady=(0, 18))

        panel = tk.Frame(
            container,
            bg=self._panel_color,
            highlightbackground=self._accent_color,
            highlightthickness=2,
            bd=0,
        )
        panel.pack(fill='both', expand=True)

        hostname_label = tk.Label(
            panel,
            text='Hostname',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', 18, 'bold'),
            anchor='center',
        )
        hostname_label.pack(fill='x', pady=(48, 6))

        hostname_value = tk.Label(
            panel,
            textvariable=self._hostname_var,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans', 24, 'bold'),
            anchor='center',
        )
        hostname_value.pack(fill='x', pady=(0, 26))

        ip_label = tk.Label(
            panel,
            text='IP адрес',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', 22, 'bold'),
            anchor='center',
        )
        ip_label.pack(fill='x', pady=(0, 8))

        ip_value = tk.Label(
            panel,
            textvariable=self._ip_var,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans Mono', 34, 'bold'),
            justify='center',
            anchor='center',
            wraplength=1200,
        )
        ip_value.pack(fill='both', expand=True, padx=28, pady=(0, 24))

        footer = tk.Label(
            panel,
            textvariable=self._status_var,
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', 16),
            anchor='center',
        )
        footer.pack(fill='x', pady=(0, 18))

    def _update_ip_addresses(self) -> None:
        addresses = discover_ipv4_addresses()
        if addresses:
            self._ip_var.set('\n'.join(addresses))
        else:
            self._ip_var.set('Сеть не подключена')

        self._status_var.set(
            f'{self._footer_text} · обновление каждые {self._refresh_ms / 1000.0:.1f} c · ESC для выхода'
        )
        if rclpy.ok():
            self._root.after(self._refresh_ms, self._update_ip_addresses)

    def _shutdown(self) -> None:
        try:
            self._root.quit()
            self._root.destroy()
        except Exception:
            pass
        if rclpy.ok():
            rclpy.shutdown()

    def run(self) -> None:
        self.get_logger().info('Touchscreen display started')
        self._root.mainloop()


def main(args: Iterable[str] | None = None) -> None:
    rclpy.init(args=args)
    node: RoverStatusDisplayNode | None = None
    try:
        node = RoverStatusDisplayNode()
        node.run()
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            try:
                node.destroy_node()
            except Exception:
                pass
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main(sys.argv)
