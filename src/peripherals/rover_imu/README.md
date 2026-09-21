# rover_imu

Serial-драйвер Yahboom YB-MRA02-V1.0 и отдельная утилита нормализации готовых IMU-сообщений.

## Запуск

После Device Manager, при свободном serial-порте:

```bash
ros2 launch rover_imu imu.launch.py
```

[config/imu.yaml](config/imu.yaml) используется нодой `yahboom_imu_node`:
`/tmp/rover_devices/imu`, 115200 baud, frame `imu_link`.
Разбор поддерживает кадры YB-MRA02 с заголовком 7E23 и старый протокол 0x55.
Наличие байтов в порту ещё не означает корректный протокол или baudrate.

## Публикации и ориентация

`/imu/data` (sensor_msgs/Imu), `/imu/mag`, `/imu/euler` и
`/imu/valid_frame_count`. Настраиваются axis_map/axis_signs, ковариации,
publish_rate_hz и data_timeout_sec. Частота в конфиге не гарантирует поступление
измерений с такой скоростью.

`publish_sensor_orientation: false` по умолчанию: нельзя считать yaw датчика
абсолютным исправным компасом только по наличию /imu/data. Ориентацию монтажа
нужно согласовать с TF и настройками EKF в rover_wheel_odometry.

## Нормализатор

`ros2 run rover_imu imu_normalizer_node` предназначен для другого драйвера,
который уже публикует `/imu/raw`; по умолчанию выход `/imu/data`.
Он не открывает serial-порт и не нужен параллельно с Yahboom-драйвером на том
же выходном топике.

Диагностика: `ros2 topic hz /imu/data`, `ros2 topic echo /imu/valid_frame_count`.
При отсутствии валидных кадров проверьте питание, порт и занят ли он другим
процессом. [Device Manager](../rover_device_manager/README.md).
