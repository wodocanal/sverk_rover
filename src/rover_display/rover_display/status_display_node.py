#!/usr/bin/env python3
from __future__ import annotations

import json
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
        self.declare_parameter('full_screen', True)
        self.declare_parameter('refresh_sec', 1.0)
        self.declare_parameter('background_color', '#07141C')
        self.declare_parameter('panel_color', '#0C202B')
        self.declare_parameter('accent_color', '#16B8F3')
        self.declare_parameter('text_color', '#F4FBFF')
        self.declare_parameter('muted_text_color', '#8CB5C7')
        self.declare_parameter('wifi_interface', 'wlan0')
        self.declare_parameter('wifi_config_script', '/usr/local/sbin/rover-wifi-config.py')
        self.declare_parameter('wifi_netplan_file', '/etc/netplan/90-rover-wifi.yaml')
        self.declare_parameter('main_menu_text', 'Hello world')

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
        self._refresh_ms = max(200, int(float(self.get_parameter('refresh_sec').value) * 1000.0))
        self._window_title = str(self.get_parameter('window_title').value)
        self._header_text = str(self.get_parameter('header_text').value)
        self._full_screen = bool(self.get_parameter('full_screen').value)
        self._background_color = str(self.get_parameter('background_color').value)
        self._panel_color = str(self.get_parameter('panel_color').value)
        self._accent_color = str(self.get_parameter('accent_color').value)
        self._text_color = str(self.get_parameter('text_color').value)
        self._muted_text_color = str(self.get_parameter('muted_text_color').value)
        self._wifi_interface = str(self.get_parameter('wifi_interface').value).strip() or 'wlan0'
        self._wifi_config_script = (
            str(self.get_parameter('wifi_config_script').value).strip()
            or '/usr/local/sbin/rover-wifi-config.py'
        )
        self._wifi_netplan_file = (
            str(self.get_parameter('wifi_netplan_file').value).strip()
            or '/etc/netplan/90-rover-wifi.yaml'
        )
        self._main_menu_text = str(self.get_parameter('main_menu_text').value).strip() or 'Hello world'

        self._networkctl_path = shutil.which('networkctl') or '/usr/bin/networkctl'
        self._sudo_path = shutil.which('sudo') or '/usr/bin/sudo'

        self._root = self._create_window()
        screen_width = max(1, int(self._root.winfo_screenwidth()))
        screen_height = max(1, int(self._root.winfo_screenheight()))
        self._ui_scale = max(0.58, min(1.0, screen_width / 1280.0, screen_height / 720.0))
        self._screen_wraplength = max(320, int(screen_width * 0.82))

        self._current_screen = 'network'
        self._apply_in_progress = False
        self._active_entry = None
        self._keyboard_shift = False

        self._hostname_var = tk.StringVar(value=socket.gethostname())
        self._ip_var = tk.StringVar(value='Поиск адреса...')
        self._ssid_var = tk.StringVar(value='')
        self._password_var = tk.StringVar(value='')
        self._network_status_var = tk.StringVar(value='Экран сетевых настроек активен')
        self._settings_status_var = tk.StringVar(value='Измени параметры сети и нажми применить.')
        self._menu_status_var = tk.StringVar(value='Главное меню')
        self._connected_ssid_var = tk.StringVar(value='SSID: —')
        self._settings_button_var = tk.StringVar(value='Настройки')

        self._build_layout()
        self._load_current_wifi_config()
        self._show_network_screen()
        self._refresh_status()

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

        container = tk.Frame(self._root, bg=self._background_color)
        container.pack(
            fill='both',
            expand=True,
            padx=self._scaled(28, minimum=12),
            pady=self._scaled(20, minimum=10),
        )

        header_frame = tk.Frame(container, bg=self._background_color)
        header_frame.pack(fill='x', pady=(0, self._scaled(14, minimum=8)))

        self._header_label = tk.Label(
            header_frame,
            text=self._header_text,
            bg=self._background_color,
            fg=self._accent_color,
            font=('DejaVu Sans', self._scaled(26, minimum=18), 'bold'),
        )
        self._header_label.pack(fill='x')

        self._settings_button = tk.Button(
            header_frame,
            textvariable=self._settings_button_var,
            command=self._open_settings_screen,
            bg=self._accent_color,
            fg=self._background_color,
            activebackground=self._text_color,
            activeforeground=self._background_color,
            font=('DejaVu Sans', self._scaled(14, minimum=10), 'bold'),
            relief='flat',
            bd=0,
            padx=self._scaled(16, minimum=8),
            pady=self._scaled(10, minimum=6),
            cursor='hand2',
        )
        self._settings_button.place(in_=header_frame, relx=1.0, rely=0.5, anchor='e')

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

        self._network_screen = tk.Frame(self._screen_container, bg=self._panel_color)
        self._settings_screen = tk.Frame(self._screen_container, bg=self._panel_color)
        self._menu_screen = tk.Frame(self._screen_container, bg=self._panel_color)

        for frame in (self._network_screen, self._settings_screen, self._menu_screen):
            frame.place(relx=0.0, rely=0.0, relwidth=1.0, relheight=1.0)

        self._build_network_screen()
        self._build_settings_screen()
        self._build_main_menu_screen()

    def _build_network_screen(self) -> None:
        tk = self._tk

        ip_title = tk.Label(
            self._network_screen,
            text='IP',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
        )
        ip_title.pack(fill='x', pady=(self._scaled(34, minimum=16), self._scaled(6, minimum=3)))

        ip_value = tk.Label(
            self._network_screen,
            textvariable=self._ip_var,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans Mono', self._scaled(28, minimum=15), 'bold'),
            justify='center',
            wraplength=self._screen_wraplength,
        )
        ip_value.pack(fill='x', padx=self._scaled(16, minimum=8))

        hostname_title = tk.Label(
            self._network_screen,
            text='Hostname',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(16, minimum=10), 'bold'),
        )
        hostname_title.pack(fill='x', pady=(self._scaled(24, minimum=10), self._scaled(6, minimum=3)))

        hostname_value = tk.Label(
            self._network_screen,
            textvariable=self._hostname_var,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans', self._scaled(22, minimum=13), 'bold'),
            justify='center',
        )
        hostname_value.pack(fill='x')

        ssid_value = tk.Label(
            self._network_screen,
            textvariable=self._connected_ssid_var,
            bg=self._panel_color,
            fg=self._accent_color,
            font=('DejaVu Sans', self._scaled(16, minimum=10), 'bold'),
            justify='center',
        )
        ssid_value.pack(fill='x', pady=(self._scaled(18, minimum=8), self._scaled(8, minimum=4)))

        status_value = tk.Label(
            self._network_screen,
            textvariable=self._network_status_var,
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(14, minimum=9)),
            justify='center',
            wraplength=self._screen_wraplength,
        )
        status_value.pack(fill='x', padx=self._scaled(20, minimum=10))

        spacer = tk.Frame(self._network_screen, bg=self._panel_color)
        spacer.pack(fill='both', expand=True)

        exit_button = tk.Button(
            self._network_screen,
            text='Выйти в главное меню',
            command=self._open_main_menu_screen,
            bg=self._accent_color,
            fg=self._background_color,
            activebackground=self._text_color,
            activeforeground=self._background_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
            relief='flat',
            bd=0,
            padx=self._scaled(20, minimum=10),
            pady=self._scaled(14, minimum=8),
            cursor='hand2',
        )
        exit_button.pack(pady=(self._scaled(10, minimum=6), self._scaled(24, minimum=12)))

    def _build_settings_screen(self) -> None:
        tk = self._tk

        title = tk.Label(
            self._settings_screen,
            text='Настройки Wi-Fi',
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans', self._scaled(24, minimum=16), 'bold'),
        )
        title.pack(fill='x', pady=(self._scaled(18, minimum=10), self._scaled(12, minimum=8)))

        form = tk.Frame(self._settings_screen, bg=self._panel_color)
        form.pack(fill='x', padx=self._scaled(20, minimum=10))

        ssid_label = tk.Label(
            form,
            text='SSID',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(16, minimum=10), 'bold'),
            anchor='w',
        )
        ssid_label.pack(fill='x', pady=(0, self._scaled(4, minimum=2)))

        self._ssid_entry = tk.Entry(
            form,
            textvariable=self._ssid_var,
            font=('DejaVu Sans', self._scaled(18, minimum=11)),
            relief='flat',
            bd=0,
            insertbackground=self._text_color,
            bg='#0F2A38',
            fg=self._text_color,
            justify='left',
        )
        self._ssid_entry.pack(fill='x', ipady=self._scaled(12, minimum=7), pady=(0, self._scaled(12, minimum=6)))
        self._ssid_entry.bind('<FocusIn>', lambda _event: self._show_keyboard(self._ssid_entry))

        password_label = tk.Label(
            form,
            text='Пароль',
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(16, minimum=10), 'bold'),
            anchor='w',
        )
        password_label.pack(fill='x', pady=(0, self._scaled(4, minimum=2)))

        self._password_entry = tk.Entry(
            form,
            textvariable=self._password_var,
            font=('DejaVu Sans', self._scaled(18, minimum=11)),
            relief='flat',
            bd=0,
            insertbackground=self._text_color,
            bg='#0F2A38',
            fg=self._text_color,
            justify='left',
            show='*',
        )
        self._password_entry.pack(fill='x', ipady=self._scaled(12, minimum=7))
        self._password_entry.bind('<FocusIn>', lambda _event: self._show_keyboard(self._password_entry))

        apply_button = tk.Button(
            self._settings_screen,
            text='Применить',
            command=self._apply_wifi_settings,
            bg=self._accent_color,
            fg=self._background_color,
            activebackground=self._text_color,
            activeforeground=self._background_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
            relief='flat',
            bd=0,
            padx=self._scaled(18, minimum=10),
            pady=self._scaled(12, minimum=8),
            cursor='hand2',
        )
        apply_button.pack(pady=(self._scaled(14, minimum=8), self._scaled(10, minimum=6)))

        settings_status = tk.Label(
            self._settings_screen,
            textvariable=self._settings_status_var,
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(14, minimum=9)),
            wraplength=self._screen_wraplength,
            justify='center',
        )
        settings_status.pack(fill='x', padx=self._scaled(18, minimum=8))

        self._keyboard_frame = tk.Frame(self._settings_screen, bg=self._panel_color)
        self._keyboard_frame.pack(side='bottom', fill='x', padx=self._scaled(14, minimum=8), pady=self._scaled(12, minimum=8))
        self._keyboard_frame.pack_forget()

        self._build_keyboard()

    def _build_main_menu_screen(self) -> None:
        tk = self._tk

        title = tk.Label(
            self._menu_screen,
            text='Главное меню',
            bg=self._panel_color,
            fg=self._accent_color,
            font=('DejaVu Sans', self._scaled(28, minimum=18), 'bold'),
        )
        title.pack(fill='x', pady=(self._scaled(34, minimum=16), self._scaled(12, minimum=8)))

        hello = tk.Label(
            self._menu_screen,
            text=self._main_menu_text,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans', self._scaled(24, minimum=14), 'bold'),
            wraplength=self._screen_wraplength,
            justify='center',
        )
        hello.pack(fill='x', padx=self._scaled(20, minimum=10), pady=(0, self._scaled(18, minimum=8)))

        ip_value = tk.Label(
            self._menu_screen,
            textvariable=self._ip_var,
            bg=self._panel_color,
            fg=self._text_color,
            font=('DejaVu Sans Mono', self._scaled(22, minimum=13), 'bold'),
            wraplength=self._screen_wraplength,
            justify='center',
        )
        ip_value.pack(fill='x', padx=self._scaled(18, minimum=8), pady=(0, self._scaled(12, minimum=6)))

        hostname_value = tk.Label(
            self._menu_screen,
            textvariable=self._hostname_var,
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(18, minimum=11), 'bold'),
            justify='center',
        )
        hostname_value.pack(fill='x')

        menu_status = tk.Label(
            self._menu_screen,
            textvariable=self._menu_status_var,
            bg=self._panel_color,
            fg=self._muted_text_color,
            font=('DejaVu Sans', self._scaled(14, minimum=9)),
            wraplength=self._screen_wraplength,
            justify='center',
        )
        menu_status.pack(fill='x', padx=self._scaled(20, minimum=10), pady=(self._scaled(18, minimum=10), 0))

    def _build_keyboard(self) -> None:
        rows = [
            list('1234567890'),
            list('qwertyuiop'),
            list('asdfghjkl'),
            ['SHIFT'] + list('zxcvbnm') + ['BACK'],
            ['@', '.', '-', '_', '/', ':', 'SPACE', 'CLEAR', 'DONE'],
        ]

        for row in rows:
            row_frame = self._tk.Frame(self._keyboard_frame, bg=self._panel_color)
            row_frame.pack(fill='x', pady=self._scaled(3, minimum=2))
            for key in row:
                button = self._tk.Button(
                    row_frame,
                    text=key if key not in {'SPACE', 'BACK'} else ('Пробел' if key == 'SPACE' else '⌫'),
                    command=lambda value=key: self._on_keyboard_key(value),
                    bg='#12384A',
                    fg=self._text_color,
                    activebackground=self._accent_color,
                    activeforeground=self._background_color,
                    font=('DejaVu Sans', self._scaled(13, minimum=9), 'bold'),
                    relief='flat',
                    bd=0,
                    padx=self._scaled(8, minimum=4),
                    pady=self._scaled(8, minimum=5),
                    cursor='hand2',
                )
                button.pack(side='left', fill='x', expand=True, padx=self._scaled(2, minimum=1))

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

    def _show_network_screen(self) -> None:
        self._current_screen = 'network'
        self._settings_button_var.set('Настройки')
        self._settings_button.configure(command=self._open_settings_screen)
        self._settings_button.place_configure(relx=1.0, rely=0.5, anchor='e')
        self._network_screen.tkraise()

    def _open_settings_screen(self) -> None:
        self._current_screen = 'settings'
        self._settings_button_var.set('Назад')
        self._settings_button.configure(command=self._show_network_screen)
        self._settings_button.place_configure(relx=1.0, rely=0.5, anchor='e')
        self._settings_screen.tkraise()

    def _open_main_menu_screen(self) -> None:
        self._current_screen = 'menu'
        self._settings_button.place_forget()
        self._menu_screen.tkraise()

    def _show_keyboard(self, entry) -> None:
        self._active_entry = entry
        if not self._keyboard_frame.winfo_manager():
            self._keyboard_frame.pack(side='bottom', fill='x', padx=self._scaled(14, minimum=8), pady=self._scaled(12, minimum=8))

    def _hide_keyboard(self) -> None:
        self._active_entry = None
        if self._keyboard_frame.winfo_manager():
            self._keyboard_frame.pack_forget()

    def _on_keyboard_key(self, key: str) -> None:
        if self._active_entry is None:
            return

        if key == 'SHIFT':
            self._keyboard_shift = not self._keyboard_shift
            return
        if key == 'BACK':
            value = self._active_entry.get()
            if value:
                self._active_entry.delete(len(value) - 1, self._tk.END)
            return
        if key == 'SPACE':
            self._active_entry.insert(self._tk.END, ' ')
            return
        if key == 'CLEAR':
            self._active_entry.delete(0, self._tk.END)
            return
        if key == 'DONE':
            self._hide_keyboard()
            self._root.focus_set()
            return

        symbol = key.upper() if self._keyboard_shift else key
        self._active_entry.insert(self._tk.END, symbol)
        if self._keyboard_shift and len(symbol) == 1 and symbol.isalpha():
            self._keyboard_shift = False

    def _networkctl_status_text(self) -> str:
        completed = self._run_command(
            [self._networkctl_path, 'status', self._wifi_interface],
            timeout=3.0,
        )
        if completed.returncode != 0:
            return ''
        return completed.stdout

    def _extract_connected_ssid(self, status_text: str) -> str:
        marker = 'Wi-Fi access point:'
        for line in status_text.splitlines():
            if marker not in line:
                continue
            after = line.split(marker, 1)[1].strip()
            if not after:
                return ''
            if ' (' in after:
                return after.split(' (', 1)[0].strip()
            return after
        return ''

    def _load_current_wifi_config(self) -> None:
        if not Path(self._wifi_config_script).exists():
            self._settings_status_var.set('Не найден helper для чтения текущей Wi-Fi конфигурации.')
            return

        completed = self._run_command(
            [self._sudo_path, '-n', self._wifi_config_script, 'current', self._wifi_interface],
            timeout=5.0,
        )
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            if 'password is required' in details.lower():
                self._settings_status_var.set('Нужен sudoers NOPASSWD для rover-wifi-config.py.')
            elif details:
                self._settings_status_var.set(details)
            return

        ssid = ''
        password = ''
        for line in completed.stdout.splitlines():
            if line.startswith('SSID='):
                ssid = line.split('=', 1)[1]
            elif line.startswith('PASSWORD='):
                password = line.split('=', 1)[1]

        if ssid:
            self._ssid_var.set(ssid)
        if password:
            self._password_var.set(password)

    def _apply_wifi_settings(self) -> None:
        if self._apply_in_progress:
            return

        ssid = self._ssid_var.get().strip()
        password = self._password_var.get()
        if not ssid:
            self._settings_status_var.set('SSID не должен быть пустым.')
            return
        if len(password) < 8:
            self._settings_status_var.set('Пароль Wi-Fi должен быть не короче 8 символов.')
            return

        self._apply_in_progress = True
        self._settings_status_var.set('Применение Wi-Fi настроек...')
        self._network_status_var.set('Применение Wi-Fi настроек...')
        self._hide_keyboard()
        self._settings_button.configure(state='disabled')

        thread = threading.Thread(
            target=self._apply_wifi_settings_worker,
            args=(ssid, password),
            daemon=True,
        )
        thread.start()

    def _apply_wifi_settings_worker(self, ssid: str, password: str) -> None:
        result = self._run_command(
            [
                self._sudo_path,
                '-n',
                self._wifi_config_script,
                'apply',
                self._wifi_interface,
                self._wifi_netplan_file,
                ssid,
                password,
            ],
            timeout=40.0,
        )

        success = result.returncode == 0
        if success:
            message = f'Сеть {ssid} применена.'
        else:
            details = result.stderr.strip() or result.stdout.strip() or 'Ошибка применения Wi-Fi.'
            if 'password is required' in details.lower():
                message = 'Нужен sudoers NOPASSWD для rover-wifi-config.py.'
            else:
                message = details

        self._root.after(
            0,
            lambda: self._finish_apply_wifi_settings(success=success, message=message),
        )

    def _finish_apply_wifi_settings(self, *, success: bool, message: str) -> None:
        self._apply_in_progress = False
        self._settings_button.configure(state='normal')
        self._settings_status_var.set(message)
        self._network_status_var.set(message)
        if success:
            self._show_network_screen()
        self._refresh_status(reschedule=False)

    def _refresh_status(self, *, reschedule: bool = True) -> None:
        addresses = discover_ipv4_addresses()
        self._ip_var.set('\n'.join(addresses) if addresses else 'Сеть не подключена')

        status_text = self._networkctl_status_text()
        connected_ssid = self._extract_connected_ssid(status_text)
        self._connected_ssid_var.set(f'SSID: {connected_ssid or "—"}')

        if self._current_screen == 'menu':
            self._menu_status_var.set(
                f'{self._main_menu_text} · SSID: {connected_ssid or "—"}'
            )
        elif not self._apply_in_progress:
            if connected_ssid:
                self._network_status_var.set(f'Подключено к сети {connected_ssid}')
            else:
                self._network_status_var.set('Сеть не подключена')

        if reschedule and rclpy.ok():
            self._root.after(self._refresh_ms, self._refresh_status)

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
