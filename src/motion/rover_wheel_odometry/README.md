# rover_wheel_odometry

Считает одометрию по четырём энкодерам и хранит запуск EKF.
Отдельного пакета rover_localization в текущей структуре нет.

## Запуск

```bash
ros2 launch rover_wheel_odometry odometry.launch.py
ros2 launch rover_wheel_odometry localization.launch.py use_imu:=true
```

Команды запускаются в разных терминалах только если эти компоненты не работают
в bringup. Для EKF без IMU используйте `use_imu:=false`.

## Поток данных

```text
/wheel/encoders -> wheel_odometry_node -> /wheel/odometry
/wheel/odometry + /imu/data -> robot_localization/ekf_node -> /odom
```

EKF публикует odom->base_link; не добавляйте второй источник такого TF.
Точный состав измерений задан в YAML фильтра.

[config/odometry.yaml](config/odometry.yaml) задаёт масштаб X/Y/yaw,
ковариации, пределы правдоподобной скорости и разрыва измерений.
Геометрия подтягивается из rover_description, параметры энкодеров из
rover_base_driver. Тип привода читает `~/.config/sverk-rover/drive_type`.

[config/localization](config/localization) содержит `ekf_with_imu.yaml` и
`ekf_wheel_only.yaml`. Standalone localization.launch выбирает один из них.
В bringup эти EKF-конфиги также принадлежат данному пакету.

Пропуски/выбросы энкодеров фильтруются, но проскальзывание не исчезает:
одометрия не заменяет локализацию по карте. Калибровку проводки выполняйте в
драйвере, а множителями одометрии корректируйте измеренный масштаб движения.

Проверка: `ros2 topic hz /wheel/odometry`, `ros2 topic hz /odom`.
