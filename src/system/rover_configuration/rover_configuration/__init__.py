"""Package-owned configuration with explicit, typed cross-package references."""

from copy import deepcopy
import os
from pathlib import Path

import yaml


def package_path(package: str, *parts: str) -> str:
    from ament_index_python.packages import get_package_share_directory

    return str(Path(get_package_share_directory(package)).joinpath(*parts))


def config_path(package: str, filename: str) -> str:
    return package_path(package, 'config', filename)


def read_config(path: str | Path, *, _stack: tuple = ()) -> dict:
    source = Path(path).expanduser().resolve()
    if source in _stack:
        raise ValueError(f'Cyclic config reference: {source}')
    data = yaml.safe_load(source.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'Expected a YAML mapping in {source}')
    return resolve_package_references(data, _stack=(*_stack, source))


def resolve_package_references(value, *, _stack: tuple = ()):
    if isinstance(value, dict):
        return {key: resolve_package_references(item, _stack=_stack)
                for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_package_references(item, _stack=_stack) for item in value]
    if not isinstance(value, str) or not value.startswith('package://'):
        return value
    target, separator, key = value.removeprefix('package://').partition('#')
    package, slash, relative = target.partition('/')
    if not slash or not relative or '..' in Path(relative).parts:
        raise ValueError(f'Invalid package reference: {value}')
    path = package_path(package, relative)
    if not separator:
        return path
    current = read_config(path, _stack=_stack)
    for part in key.split('.'):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f'Unknown config reference: {value}')
        current = current[part]
    return deepcopy(current)


def node_parameters(path: str | Path, node: str) -> dict:
    data = read_config(path)
    parameters = data.get(node, {}).get('ros__parameters')
    if not isinstance(parameters, dict):
        raise ValueError(f'Missing {node}.ros__parameters in {path}')
    return parameters


def resolve_runtime_references(value, sources=None):
    sources = sources or {}
    if isinstance(value, dict):
        return {k: resolve_runtime_references(v, sources) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve_runtime_references(v, sources) for v in value]
    if not isinstance(value, str) or not value.startswith('@'):
        return value
    if value.startswith('@env.'):
        return os.environ.get(value[5:], '')
    result = sources
    for key in value[1:].split('.'):
        if not isinstance(result, dict) or key not in result:
            raise KeyError(f'Unknown runtime reference: {value}')
        result = result[key]
    return deepcopy(result)


def environment_overrides(parameters, variables):
    result = deepcopy(parameters)
    for parameter, (names, convert) in variables.items():
        for name in names.split('|'):
            if name in os.environ:
                result[parameter] = convert(os.environ[name])
                break
    return result
