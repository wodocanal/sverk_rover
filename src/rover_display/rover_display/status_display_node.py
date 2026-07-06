#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
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
        self.declare_parameter('wifi_interface', 'wlan0')
        self.declare_parameter('wifi_uplink_connection', '')
        self.declare_parameter('wifi_hotspot_connection', 'rover-ap')
        self.declare_parameter('wifi_hotspot_ssid', 'Rover-AP')
        self.declare_parameter('wifi_hotspot_password', 'StrongPassword123')
        self.declare_parameter('wifi_hotspot_address', '192.168.50.1/24')
        self.declare_parameter('wifi_hotspot_dhcp_range', '192.168.50.10,192.168.50.200')
        self.declare_parameter('wifi_hotspot_band', 'bg')
        self.declare_parameter('wifi_hotspot_channel', 1)

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

        self._wifi_interface = str(self.get_parameter('wifi_interface').value).strip() or 'wlan0'
        self._wifi_uplink_connection = (
            str(self.get_parameter('wifi_uplink_connection').value).strip()
        )
        self._wifi_hotspot_connection = (
            str(self.get_parameter('wifi_hotspot_connection').value).strip() or 'rover-ap'
        )
        self._wifi_hotspot_ssid = (
            str(self.get_parameter('wifi_hotspot_ssid').value).strip() or 'Rover-AP'
        )
        self._wifi_hotspot_password = (
            str(self.get_parameter('wifi_hotspot_password').value).strip()
            or 'StrongPassword123'
        )
        self._wifi_hotspot_address = (
            str(self.get_parameter('wifi_hotspot_address').value).strip()
            or '192.168.50.1/24'
        )
        self._wifi_hotspot_dhcp_range = (
            str(self.get_parameter('wifi_hotspot_dhcp_range').value).strip()
            or '192.168.50.10,192.168.50.200'
        )
        self._wifi_hotspot_band = (
            str(self.get_parameter('wifi_hotspot_band').value).strip() or 'bg'
        )
        self._wifi_hotspot_channel = int(self.get_parameter('wifi_hotspot_channel').value)
        self._nmcli_path = shutil.which('nmcli') or (
            '/usr/bin/nmcli' if Path('/usr/bin/nmcli').exists() else ''
        )

        self._root = self._create_window()
        screen_width = max(1, int(self._root.winfo_screenwidth()))
        screen_height = max(1, int(self._root.winfo_screenheight()))
        self._ui_scale = max(0.58, min(1.0, screen_width / 1280.0, screen_height / 720.0))
        self._screen_wraplength = max(360, int(screen_width * 0.82))
        self._screen_mode = 'main'
        self._wifi_switch_in_progress = False

        self._hostname_var = tk.StringVar(value=socket.gethostname())
        self._ip_var = tk.StringVar(value='Поиск адреса...')
        self._status_var = tk.StringVar(value='Экран ровера активен')
        self._wifi_mode_var = tk.StringVar(value='Определение режима Wi-Fi...')
        self._settings_wifi_mode_var = tk.StringVar(value='Определение режима Wi-Fi...')
        self._settings_status_var = tk.StringVar(value='Выберите режим и нажмите подтвердить.')
        self._screen_button_var = tk.StringVar(value='Настройки')
        self._selected_wifi_mode_var = tk.StringVar(value='connect')

        self._build_layout()
        self._show_main_screen()
        self._refresh_display_data()

    def _scaled(self, value: int, *, minimum: int = 1) -> int:
        return max(minimum, int(round(value * self._ui_scale)))

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
        container.pack(
            fill='both',
            expand=True,
            padx=self._scaled(36, minimum=12),
            pady=self._scaled(28, minimum=10),
        )

        header_frame = tk.Frame(container, bg=self._background_color)
        header_frame.pack(fill='x', pady=(0, self._scaled(18, minimum=8)))

        header = tk.Label(
            header_frame,
            text=self._header_text,
            bg=self._background_color,
            fg=self._accent_color,
            font=('DejaVu Sans', self._scaled(32, minimum=18), 'bold'),
            anchor='center',
        )
        header.pack(fill='x')

        self._screen_button = tk.Button(
            header_frame,
            textvariable=self._screen_button_var,
            command=self._toggle_settings_screen,
            bg=self._accent_color,
            fg=self._background_color,
            activebackground=self._text_color,
            activeforeground=self._background_color,
            font=('DejaVu Sans', self._scaled(16, minimum=10), 'bold'),
            relief='flat',
            bd=0,
            padx=self._scaled(18, minimum=8),
            pady=self._scaled(10, minimum=6),
            highlightthickness=0,
            cursor='hand2',
        )
        self._screen_button.place(relx=1.0, rely=0.5, anchor='e')

        panel = tk.Frame(
            container,
            bg=self._panel_color,
            highlightbackground=self._accent_color,
            highlightthickness=2,
            bd=0,
        )
        panel.pack(fill='both', expand=True)

        self._screen_container = tk.Frame(panel, bg=self._panel_color)
        self._screen_container.pack(fill='both', expand=True)

        self._main_screen = tk.Frame(self._screen_container, bg=self._panel_color)
        self._settings_screen = tk.Frame(self._screen_container, bg=self._panel_color)

        for frame in (self._main_screen, self._settings_screen):
            frame.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)

        self._build_main_screen()
        self._build_settings_screen()

    def _build_main_screen(self) -> None:
        tk = self._tk
        panel = self._main_screen

        hostname_label = tk.Label(
            panel,
            text='Hostname',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
            anchor='center',
        )
        hostname_label.pack(
            fill='x',
            pady=(self._scaled(40, minimum=16), self._scaled(6, minimum=3)),
        )

        hostname_value = tk.Label(
            panel,
            textvariable=self._hostname_var,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans', self._scaled(24, minimum=14), 'bold'),
            anchor='center',
        )
        hostname_value.pack(fill='x', pady=(0, self._scaled(20, minimum=8)))

        wifi_mode_label = tk.Label(
            panel,
            text='Текущий режим Wi-Fi',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
            anchor='center',
        )
        wifi_mode_label.pack(fill='x', pady=(0, self._scaled(6, minimum=3)))

        wifi_mode_value = tk.Label(
            panel,
            textvariable=self._wifi_mode_var,
            bg=self._panel_color,
            fg=self._accent_color,
            font=('DejaVu Sans', self._scaled(24, minimum=14), 'bold'),
            anchor='center',
        )
        wifi_mode_value.pack(fill='x', pady=(0, self._scaled(18, minimum=8)))

        ip_label = tk.Label(
            panel,
            text='IP адрес',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(20, minimum=12), 'bold'),
            anchor='center',
        )
        ip_label.pack(fill='x', pady=(0, self._scaled(8, minimum=4)))

        ip_value = tk.Label(
            panel,
            textvariable=self._ip_var,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans Mono', self._scaled(26, minimum=14), 'bold'),
            justify='center',
            anchor='center',
            wraplength=self._screen_wraplength,
        )
        ip_value.pack(
            fill='both',
            expand=True,
            padx=self._scaled(24, minimum=10),
            pady=(0, self._scaled(16, minimum=6)),
        )

        footer = tk.Label(
            panel,
            textvariable=self._status_var,
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(15, minimum=9)),
            anchor='center',
        )
        footer.pack(fill='x', pady=(0, self._scaled(14, minimum=6)))

    def _build_settings_screen(self) -> None:
        tk = self._tk
        panel = self._settings_screen

        settings_title = tk.Label(
            panel,
            text='Настройки Wi-Fi',
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans', self._scaled(26, minimum=16), 'bold'),
            anchor='center',
        )
        settings_title.pack(
            fill='x',
            pady=(self._scaled(34, minimum=14), self._scaled(16, minimum=8)),
        )

        current_mode_label = tk.Label(
            panel,
            text='Текущий режим',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
            anchor='center',
        )
        current_mode_label.pack(fill='x', pady=(0, self._scaled(6, minimum=3)))

        current_mode_value = tk.Label(
            panel,
            textvariable=self._settings_wifi_mode_var,
            bg=self._panel_color,
            fg=self._accent_color,
            font=('DejaVu Sans', self._scaled(22, minimum=13), 'bold'),
            anchor='center',
        )
        current_mode_value.pack(fill='x', pady=(0, self._scaled(20, minimum=8)))

        options_frame = tk.Frame(panel, bg=self._panel_color)
        options_frame.pack(
            fill='x',
            padx=self._scaled(60, minimum=14),
            pady=(0, self._scaled(18, minimum=8)),
        )

        for value, label_text in (
            ('connect', 'Подключаться к сети'),
            ('share', 'Раздавать свой Wi-Fi'),
        ):
            button = tk.Radiobutton(
                options_frame,
                text=label_text,
                variable=self._selected_wifi_mode_var,
                value=value,
                indicatoron=False,
                bg=self._panel_color,
                fg=self._text_color,
                activebackground=self._accent_color,
                activeforeground=self._background_color,
                selectcolor=self._accent_color,
                font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
                relief='groove',
                bd=2,
                highlightthickness=2,
                highlightbackground=self._accent_color,
                highlightcolor=self._accent_color,
                padx=self._scaled(14, minimum=8),
                pady=self._scaled(14, minimum=8),
                cursor='hand2',
            )
            button.pack(fill='x', pady=self._scaled(8, minimum=4))

        apply_button = tk.Button(
            panel,
            text='Подтвердить',
            command=self._request_apply_wifi_mode,
            bg=self._accent_color,
            fg=self._background_color,
            activebackground=self._text_color,
            activeforeground=self._background_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
            relief='flat',
            bd=0,
            padx=self._scaled(22, minimum=10),
            pady=self._scaled(12, minimum=8),
            cursor='hand2',
        )
        apply_button.pack(pady=(self._scaled(8, minimum=4), self._scaled(16, minimum=8)))

        status_label = tk.Label(
            panel,
            textvariable=self._settings_status_var,
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(15, minimum=9)),
            justify='center',
            wraplength=self._screen_wraplength,
            anchor='center',
        )
        status_label.pack(
            fill='x',
            padx=self._scaled(30, minimum=10),
            pady=(0, self._scaled(16, minimum=8)),
        )

    def _run_command(self, command: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return subprocess.CompletedProcess(command, 127, '', 'command not found')

    def _nmcli_available(self) -> bool:
        return bool(self._nmcli_path)

    def _wifi_connectivity_state(self) -> str:
        completed = self._run_command(
            [self._nmcli_path, '-t', '-f', 'CONNECTIVITY', 'general', 'status'],
            timeout=2.0,
        )
        if completed.returncode != 0:
            return 'unknown'
        return completed.stdout.strip() or 'unknown'

    def _active_wifi_connection(self) -> str:
        completed = self._run_command(
            [self._nmcli_path, '-g', 'GENERAL.CONNECTION', 'device', 'show', self._wifi_interface],
            timeout=2.0,
        )
        if completed.returncode != 0:
            return ''
        value = completed.stdout.strip()
        if value in {'', '--'}:
            return ''
        return value

    def _current_wifi_mode_key(self) -> str:
        if not self._nmcli_available():
            return 'unknown'

        active_connection = self._active_wifi_connection()
        if active_connection == self._wifi_hotspot_connection:
            return 'share'
        if active_connection:
            return 'connect'

        connectivity = self._wifi_connectivity_state()
        if connectivity == 'full':
            return 'connect'
        return 'disconnected'

    def _wifi_mode_label(self, mode_key: str) -> str:
        if mode_key == 'connect':
            return 'Подключение к сети'
        if mode_key == 'share':
            return 'Раздача Wi-Fi'
        if mode_key == 'disconnected':
            return 'Wi-Fi не активен'
        return 'Режим недоступен'

    def _toggle_settings_screen(self) -> None:
        if self._screen_mode == 'settings':
            self._show_main_screen()
        else:
            self._show_settings_screen()

    def _show_main_screen(self) -> None:
        self._screen_mode = 'main'
        self._screen_button_var.set('Настройки')
        self._main_screen.tkraise()

    def _show_settings_screen(self) -> None:
        self._screen_mode = 'settings'
        self._screen_button_var.set('Назад')
        mode_key = self._current_wifi_mode_key()
        if not self._wifi_switch_in_progress:
            self._selected_wifi_mode_var.set('share' if mode_key == 'share' else 'connect')
            self._settings_status_var.set('Выберите режим и нажмите подтвердить.')
        self._settings_screen.tkraise()

    def _ensure_hotspot_profile(self) -> tuple[bool, str]:
        if len(self._wifi_hotspot_password) < 8:
            return False, 'Пароль точки доступа должен быть не короче 8 символов.'

        existing = self._run_command(
            [self._nmcli_path, '-t', '-f', 'NAME', 'connection', 'show'],
            timeout=3.0,
        )
        if existing.returncode != 0:
            details = existing.stderr.strip() or existing.stdout.strip() or 'nmcli error'
            return False, f'Не удалось получить список профилей: {details}'

        existing_names = {
            line.strip() for line in existing.stdout.splitlines() if line.strip()
        }

        if self._wifi_hotspot_connection not in existing_names:
            created = self._run_command(
                [
                    self._nmcli_path,
                    'connection',
                    'add',
                    'type',
                    'wifi',
                    'ifname',
                    self._wifi_interface,
                    'mode',
                    'ap',
                    'con-name',
                    self._wifi_hotspot_connection,
                    'ssid',
                    self._wifi_hotspot_ssid,
                ],
                timeout=8.0,
            )
            if created.returncode != 0:
                details = created.stderr.strip() or created.stdout.strip() or 'nmcli error'
                return False, f'Не удалось создать профиль точки доступа: {details}'

        updated = self._run_command(
            [
                self._nmcli_path,
                'connection',
                'modify',
                self._wifi_hotspot_connection,
                'connection.interface-name',
                self._wifi_interface,
                'connection.autoconnect',
                'no',
                '802-11-wireless.mode',
                'ap',
                '802-11-wireless.band',
                self._wifi_hotspot_band,
                '802-11-wireless.channel',
                str(self._wifi_hotspot_channel),
                '802-11-wireless.ssid',
                self._wifi_hotspot_ssid,
                'ipv4.method',
                'shared',
                'ipv4.addresses',
                self._wifi_hotspot_address,
                'ipv4.shared-dhcp-range',
                self._wifi_hotspot_dhcp_range,
                'ipv6.method',
                'disabled',
                'wifi-sec.key-mgmt',
                'wpa-psk',
                'wifi-sec.psk',
                self._wifi_hotspot_password,
            ],
            timeout=8.0,
        )
        if updated.returncode != 0:
            details = updated.stderr.strip() or updated.stdout.strip() or 'nmcli error'
            return False, f'Не удалось настроить точку доступа: {details}'

        return True, 'Профиль точки доступа готов.'

    def _request_apply_wifi_mode(self) -> None:
        if self._wifi_switch_in_progress:
            return

        desired_mode = self._selected_wifi_mode_var.get().strip() or 'connect'
        self._wifi_switch_in_progress = True
        self._settings_status_var.set('Применение настроек Wi-Fi...')
        self._status_var.set('Применение настроек Wi-Fi...')
        self._screen_button.configure(state='disabled')

        worker = threading.Thread(
            target=self._apply_wifi_mode_worker,
            args=(desired_mode,),
            daemon=True,
        )
        worker.start()

    def _apply_wifi_mode_worker(self, desired_mode: str) -> None:
        success = False
        message = 'Неизвестная ошибка'

        try:
            if not self._nmcli_available():
                message = 'nmcli не найден. Установи и включи NetworkManager.'
            elif desired_mode == 'connect':
                success, message = self._activate_uplink_mode()
            elif desired_mode == 'share':
                success, message = self._activate_hotspot_mode()
            else:
                message = 'Неизвестный режим Wi-Fi.'
        except Exception as exc:  # pragma: no cover - subprocess/platform specific
            message = f'Ошибка переключения Wi-Fi: {exc}'

        self._root.after(
            0,
            lambda: self._finish_apply_wifi_mode(
                success=success,
                desired_mode=desired_mode,
                message=message,
            ),
        )

    def _activate_uplink_mode(self) -> tuple[bool, str]:
        if not self._wifi_uplink_connection:
            return False, 'Не задан параметр wifi_uplink_connection.'

        self._run_command([self._nmcli_path, 'radio', 'wifi', 'on'], timeout=4.0)
        self._run_command(
            [self._nmcli_path, 'connection', 'down', 'id', self._wifi_hotspot_connection],
            timeout=6.0,
        )
        completed = self._run_command(
            [
                self._nmcli_path,
                'connection',
                'up',
                'id',
                self._wifi_uplink_connection,
                'ifname',
                self._wifi_interface,
            ],
            timeout=15.0,
        )
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip() or 'nmcli error'
            return False, f'Не удалось подключиться к сети: {details}'
        return True, f'Подключение к сети включено: {self._wifi_uplink_connection}'

    def _activate_hotspot_mode(self) -> tuple[bool, str]:
        ensured, ensure_message = self._ensure_hotspot_profile()
        if not ensured:
            return False, ensure_message

        self._run_command([self._nmcli_path, 'radio', 'wifi', 'on'], timeout=4.0)
        if self._wifi_uplink_connection:
            self._run_command(
                [self._nmcli_path, 'connection', 'down', 'id', self._wifi_uplink_connection],
                timeout=6.0,
            )
        completed = self._run_command(
            [
                self._nmcli_path,
                'connection',
                'up',
                'id',
                self._wifi_hotspot_connection,
                'ifname',
                self._wifi_interface,
            ],
            timeout=15.0,
        )
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip() or 'nmcli error'
            return False, f'Не удалось включить точку доступа: {details}'
        return True, f'Точка доступа включена: {self._wifi_hotspot_ssid}'

    def _finish_apply_wifi_mode(
        self,
        *,
        success: bool,
        desired_mode: str,
        message: str,
    ) -> None:
        self._wifi_switch_in_progress = False
        self._screen_button.configure(state='normal')
        self._settings_status_var.set(message)
        self._status_var.set(message)

        if success:
            self._selected_wifi_mode_var.set(desired_mode)
            self._show_main_screen()

        self._refresh_display_data(reschedule=False)

    def _refresh_display_data(self, *, reschedule: bool = True) -> None:
        addresses = discover_ipv4_addresses()
        if addresses:
            self._ip_var.set('\n'.join(addresses))
        else:
            self._ip_var.set('Сеть не подключена')

        mode_key = self._current_wifi_mode_key()
        mode_label = self._wifi_mode_label(mode_key)
        self._wifi_mode_var.set(mode_label)
        self._settings_wifi_mode_var.set(mode_label)

        if self._screen_mode == 'settings' and not self._wifi_switch_in_progress:
            self._selected_wifi_mode_var.set('share' if mode_key == 'share' else 'connect')

        if not self._wifi_switch_in_progress:
            self._status_var.set(
                f'{self._footer_text} · обновление каждые {self._refresh_ms / 1000.0:.1f} c · ESC для выхода'
            )

        if reschedule and rclpy.ok():
            self._root.after(self._refresh_ms, self._refresh_display_data)

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
