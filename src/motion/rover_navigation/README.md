# rover_navigation

Launch и конфиги SLAM Toolbox/Nav2, пользовательские параметры навигации,
CLI сохранения и выбора карт. Драйверы и одометрия запускаются отдельно.

## Обычный запуск

С `rover-bringup` в full и отдельным `rover-web` используйте
**Движение -> Визуализация**. Не дублируйте этот стек ручным launch.
[Пошаговое руководство](../../../docs/web-navigation.md).

## Standalone

При работающих датчиках, одометрии, TF и корректной цепочке cmd_vel:

```bash
ros2 launch rover_navigation slam.launch.py
# Альтернативный режим, не одновременно со SLAM:
ros2 launch rover_navigation navigation.launch.py
```

Nav2 публикует в `/cmd_vel_nav`; нужен twist_mux или эквивалентная согласованная
маршрутизация к драйверу. Standalone пакет не запускает моторы/mux.
Nav2 включает map_server, AMCL, planner/controller/smoother, behavior server,
BT navigator, waypoint follower и lifecycle managers.
SLAM запускает async_slam_toolbox_node с lifecycle manager.

[config/nav2.yaml](config/nav2.yaml), [config/slam_toolbox.yaml](config/slam_toolbox.yaml).
Аргументы включают `params_file`, `settings_file`, `drive_type_file`,
`use_sim_time`, `use_rviz`, `autostart`; для Nav2 также `map`.
Проверить конкретный launch: `ros2 launch rover_navigation navigation.launch.py --show-args`.

`~/.config/sverk-rover/navigation.yaml` хранит изменения из веба; они применяются
через временный YAML и могут перекрывать params_file. Без сохранённого файла
используются пакетные настройки. Differential запрещает боковое движение.
Ограничения базы остаются дополнительными ограничениями над настройками Nav2.

## Карты

```bash
ros2 run rover_navigation rover_map save room
ros2 run rover_navigation rover_map list
ros2 run rover_navigation rover_map status
ros2 run rover_navigation rover_map use ARCHIVE_DIRECTORY
```

Замените ARCHIVE_DIRECTORY именем из list. Save выполняется при работающем SLAM.
[Каталог карт](maps/README.md) описывает current/archive и `ROVER_MAPS_ROOT`.
Выбор карты в вебе передаёт её путь в Nav2 без замены current; команда use
наоборот выбирает архив как текущую карту.

Полное сохранение включает occupancy YAML/PGM, posegraph/data и метаданные.
CLI `--occupancy-only` не даёт графа для продолжения mapping. Веб сохраняет
полный набор. В стандартном расположении файлы синхронизируются с installed
share; перекомпиляция ради сохранения карты не требуется. При внешнем
ROVER_MAPS_ROOT installed share не меняется: явно передавайте путь карты в Nav2.

## Продолжение картографии

При наличии .posegraph/.data и работающем оборудовании:

```bash
ros2 launch rover_navigation update_map.launch.py start_mode:=given initial_x:=1.2 initial_y:=0.5 initial_yaw:=1.57
```

Координаты в метрах, yaw в радианах; поза должна соответствовать реальному старту.
Не запускайте одновременно с AMCL/Nav2. После обновления сохраните новую карту.
