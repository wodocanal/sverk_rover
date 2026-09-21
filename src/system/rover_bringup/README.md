# rover_bringup

Композиция ровера: выбирает профиль, обнаруживает serial-устройства и подключает
launch-файлы пакетов. Не является владельцем настроек каждого драйвера.

## Запуск

После сборки и source workspace, при остановленных дублирующих сервисах:

```bash
ros2 launch rover_bringup robot.launch.py profile:=full
ros2 launch rover_bringup robot.launch.py profile:=full use_display:=false
ros2 launch rover_bringup robot.launch.py --show-args
```

Рабочие профили: [config/profiles](config/profiles). `full` включает оборудование,
локализацию, камеру/vision, ленту, UI, агента и MQTT. Nav2/SLAM выключены и
запускаются из веба. Vision-нода включена в состав, но её обработка по умолчанию
выключена в собственном конфиге. Octoliner/аудио в full выключены.

## Launch-файлы

| Файл | Назначение |
| --- | --- |
| `robot.launch.py` | Основная композиция, profile и use_* overrides |
| `hardware.launch.py` | Обёртка аппаратного профиля |
| `peripherals.launch.py` | Композиция периферийных драйверов |
| `ui.launch.py` | Web/display/rosboard из отдельного ui.yaml |
| `mapping.launch.py` | Аппаратный запуск и SLAM |
| `navigation.launch.py` | Аппаратный запуск и Nav2 |
| `update_map.launch.py` | Продолжение сохранённого posegraph |

`ui.yaml` использует секцию `ui`, а остальные профили `components`.
Не считайте его эквивалентом `profile:=ui`. Флаги `use_nav2` и `use_slam`
существуют, но не включайте их в full при управлении этими процессами из веба.

## Конфигурация и systemd

[Полное руководство](config/README.md) содержит владельцев конфигов и приоритеты.
Внешние узлы robot_state_publisher, robot_localization, twist_mux, Nav2,
SLAM Toolbox, RViz поставляются ROS-зависимостями, а не копируются в src.

`rover-bringup.service` отключает web/rosboard независимо от их флагов профиля;
`rover-web.service` поднимает их отдельно. Экран остаётся в bringup.
Сервисы и обновление: [operations.md](../../../docs/operations.md).

Не запускайте полный launch поверх сервиса: возможны конфликты портов и моторов.
Тесты в [test](test) проверяют конфигурацию с подменой discovery, без движения.
