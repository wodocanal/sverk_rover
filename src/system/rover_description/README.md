# rover_description

Упрощённая модель ровера, общие идентичность/геометрия и настройки RViz.

## Конфиги и модель

- [config/rover_v1.yaml](config/rover_v1.yaml): `robot.id`, hostname,
  serial_number, размеры корпуса/колёс, положение и поворот IMU/лидара.
- [urdf/rover.urdf.xacro](urdf/rover.urdf.xacro): геометрия и сочленения.
- [rviz](rviz): готовые представления для отдельных задач.

Пакетный launch читает геометрию YAML и передаёт её аргументами xacro.
Драйвер и одометрия ссылаются на тот же YAML. Файл не меняет Linux hostname;
это отдельная административная операция. Robot ID агента и моста должен совпадать.

## Запуск

```bash
ros2 launch rover_description description.launch.py
ros2 launch rover_description display_model.launch.py
```

Первый запускает `robot_state_publisher`; для вращающихся сочленений нужны
`/joint_states` от драйвера или соответствующего тестового издателя.
Не запускайте второй robot_state_publisher поверх bringup.

Дополнительные RViz launch: `display_lidar.launch.py`, `display_odom.launch.py`,
`display_slam.launch.py`, `display_navigation.launch.py`. Наличие визуализатора
не запускает соответствующие физические датчики или полный Nav2.

## Ограничения

URDF описывает простую геометрию, а не готовую физическую Gazebo-модель.
Выбор differential-привода меняет кинематику драйвера/одометрии, не автоматически
внешний вид колёс в xacro. Изменение геометрии требует согласования footprint,
фильтра лидара и навигационных параметров.

[Настройка нового экземпляра](../../../docs/rover-image-clone-setup.md).
