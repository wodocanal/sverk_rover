# rover_interfaces

Общие ROS-типы и реестр имён. Пакет ament_cmake генерирует Python/C++ интерфейсы
через rosidl. Собственной ноды и launch-файла нет.

## Содержимое

- [msg](msg): `WheelCommand`, `WheelEncoders`, `LEDState`, `LEDStateArray`,
  `LedStripState`, `OctolinerReading`.
- [srv](srv): `CalibrateMotors`, `GetFrame`, `SetLEDEffect`, `SetLEDs`,
  `SetLedStripState`, `SetSensitivity`, `SpeakText`.
- [config/topics.yaml](config/topics.yaml): общие топики и TF-фреймы.

В текущем пакете нет собственных action-определений; навигация использует
`nav2_msgs/action/NavigateToPose`. Точные поля и единицы смотрите в .msg/.srv,
не подменяйте типы JSON-строками без контракта соответствующего компонента.

## Сборка и просмотр

```bash
colcon build --packages-up-to rover_interfaces
source install/setup.bash
ros2 interface show rover_interfaces/srv/CalibrateMotors
ros2 interface show rover_interfaces/msg/WheelEncoders
```

Это пример обычного install; сохраняйте режим сборки существующего workspace.
После изменения интерфейсов пересоберите и перезапустите их потребителей.

Реестр имён сам не создаёт издателей. Например, наличие `battery_state` в YAML
не означает, что кто-то публикует BatteryState. Не все ноды автоматически
используют весь реестр; проверьте ссылки package:// и аргументы launch.
