from __future__ import annotations

import os
from pathlib import Path


MECANUM = 'mecanum'
DIFFERENTIAL = 'differential'
DRIVE_TYPES = (MECANUM, DIFFERENTIAL)
DEFAULT_DRIVE_TYPE_FILE = '~/.config/sverk-rover/drive_type'


def normalize_drive_type(value: object) -> str:
    drive_type = str(value).strip().lower()
    if drive_type not in DRIVE_TYPES:
        expected = ', '.join(DRIVE_TYPES)
        raise ValueError(f'drive_type must be one of: {expected}')
    return drive_type


def drive_type_path(value: object = DEFAULT_DRIVE_TYPE_FILE) -> Path:
    return Path(str(value)).expanduser()


def read_drive_type(path: object, fallback: object = MECANUM) -> str:
    default = normalize_drive_type(fallback)
    resolved = drive_type_path(path)
    try:
        value = resolved.read_text(encoding='utf-8').strip()
    except FileNotFoundError:
        return default
    except OSError as exc:
        raise RuntimeError(f'Cannot read drive type from {resolved}: {exc}') from exc
    return normalize_drive_type(value or default)


def write_drive_type(path: object, value: object) -> Path:
    drive_type = normalize_drive_type(value)
    resolved = drive_type_path(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    temporary = resolved.with_name(f'.{resolved.name}.{os.getpid()}.tmp')
    try:
        temporary.write_text(f'{drive_type}\n', encoding='utf-8')
        os.replace(temporary, resolved)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    return resolved
