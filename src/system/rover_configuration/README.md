# rover_configuration

Python-библиотека загрузки пакетных конфигов и создания простых launch-файлов.
Собственных ROS-нод, топиков и рабочего аппаратного YAML нет.

## API

[rover_configuration/__init__.py](rover_configuration/__init__.py):
`package_path`, `config_path`, `read_config`, `node_parameters`,
`resolve_package_references`, `resolve_runtime_references`, `environment_overrides`.

`package://rover_description/config/rover_v1.yaml#geometry.wheel_radius_m`
читает типизированное значение YAML. Ссылка без `#` возвращает путь внутри
установленного share пакета. Пакеты ищутся через ament index: workspace должен
быть собран и подключён. Неизвестные ключи и циклические ссылки вызывают ошибки.

`@env.NAME` и `@mcp.url` разрешаются отдельным вызовом runtime resolver,
например в launch агента. Это не встроенная возможность ROS YAML.

## Использование в launch

```python
from rover_configuration.launch import node_launch

def generate_launch_description():
    return node_launch(
        'rover_camera', 'usb_camera_node', 'usb_camera_node', 'camera.yaml',
    )
```

Обёртка читает рабочий YAML и объявляет `config_file` и аргументы параметров
из исходного конфига. Явные аргументы перекрывают YAML; типы проверяются.
Не все сложные launch используют эту обёртку: смотрите `--show-args`.

## Проверка

Из корня workspace:

```bash
python3 -m unittest discover -s src/system/rover_configuration/test -v
```

Политика владения и сохранённые overrides: [Configuration Guide](../rover_bringup/config/README.md).
