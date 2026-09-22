# rover_base_driver

Драйвер четырёхканального Quad-MD: преобразует Twist в скорости колёс,
читает энкодеры и напряжение питания. Поддерживает mecanum и differential.

## Запуск

После настройки устройств и остановки другого владельца контроллера:

```bash
ros2 launch rover_base_driver base.launch.py
ros2 launch rover_base_driver base.launch.py --show-args
```

[config/base.yaml](config/base.yaml) задаёт serial_device, baudrate, тип
привода, перестановку/знаки моторов и энкодеров, пределы скорости, ускорений
и таймауты. Геометрия читается ссылками из rover_description. По умолчанию
используется `/tmp/rover_devices/motor_controller`, 115200 baud.

## Интерфейсы

| Вход/выход | Тип и назначение |
| --- | --- |
| `/cmd_vel` | geometry_msgs/Twist, команда движения |
| `/wheel/encoders` | rover_interfaces/WheelEncoders |
| `/drive/wheel_commands` | rover_interfaces/WheelCommand |
| `/joint_states` | sensor_msgs/JointState |
| `/drive/wheel_speeds/measured` | std_msgs/Float64MultiArray |
| `/battery_voltage` | std_msgs/Float32, напряжение, не процент заряда |
| `/drive/calibrate_motors` | rover_interfaces/srv/CalibrateMotors |

При differential боковая составляющая запрещена. Тип привода сохраняется в
`~/.config/sverk-rover/drive_type`, калибровка в
`~/.config/sverk-rover/motor_calibration.json`; сохранённые данные перекрывают
соответствующие стартовые параметры. После калибровки требуется перезапуск.

## Безопасность и mux

Есть таймаут команд, контроль свежести обратной связи, ограничения ускорения и
калибровочные импульсы с ограниченной длительностью. Это не аппаратный e-stop.
Калибруйте только с поднятыми колёсами; [веб-мастер](../../../docs/web-hardware-setup.md).

[config/twist_mux.yaml](config/twist_mux.yaml) задаёт приоритеты navigation,
test/agent и teleop. Сам twist_mux внешний ROS-пакет, запускаемый bringup по
флагу, а не автоматически этим standalone launch.
`configure_motor_board` меняет настройки контроллера; это не обязательный
шаг каждого запуска. Перед использованием изучите его `--help`.
