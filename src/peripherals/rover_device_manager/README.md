# rover_device_manager

Назначает serial-устройства ролям Quad-MD, Yahboom YB-MRA02-V1.0 и
SLLIDAR/RPLIDAR. Это CLI/библиотека для bringup и веб-мастера, не постоянно
работающая нода с универсальным мониторингом всей периферии.

## Первичная настройка

Остановите bringup и другие владельцы serial-портов. Веб можно оставить
отдельно для работы мастера. Поднимите колёса:

```bash
ros2 run rover_device_manager setup_devices
```

Мастер просит отключить три устройства, затем подключать по одному, проверяет
протоколы и сохраняет `~/.config/rover/devices.json`. Для лидара пробуется
официальный SDK, затем прямой запрос. CLI допускает явное принятие IMU без
проверки; это не подтверждение исправной передачи данных. Веб требует проверки.

## Подготовка перед запуском

```bash
ros2 run rover_device_manager discover_devices --mode configured --require-imu --require-lidar
ros2 run rover_device_manager discover_devices --mode verify --require-imu --require-lidar
```

- `configured`: сохранённые пути/идентичность с поиском при перемещении устройства.
- `verify`: дополнительно протокольная проверка.
- `full`: полный поиск по serial-портам; используйте осознанно при свободных портах.

[config/device_manager.yaml](config/device_manager.yaml) задаёт политику
bringup, config path и runtime directory. У CLI есть собственные аргументы
`--config`, `--runtime-dir`; для нестандартного пути передавайте их явно.

Ссылки создаются в `/tmp/rover_devices/{motor_controller,imu,lidar}`.
Они временные и восстанавливаются при запуске. Перестановка USB/использование
хаба поддерживается поиском идентичности/протокола, но одинаковые адаптеры
без уникального serial могут оставаться неоднозначными. Не угадывайте роль по ttyUSB0.

Камера, лента, I2C, аудио и экран не проверяются этим serial-мастером.
[Веб-настройка и резервные копии](../../../docs/web-hardware-setup.md).
