# Документация Sverk Rover

Начните с [корневого README](../README.md). Команды в руководствах выполняются
из корня собранного workspace после `source /opt/ros/jazzy/setup.bash` и
`source install/setup.bash`, если явно не сказано иначе. Для shell используйте
Bash; systemd не читает настройки интерактивного терминала.

## Руководства оператора

| Задача | Руководство |
| --- | --- |
| Установка, запуск, обновление, логи | [Эксплуатация](operations.md) |
| Где менять параметры и как они применяются | [Конфигурация](../src/system/rover_bringup/config/README.md) |
| Новый ровер или клонированный образ | [Настройка экземпляра](rover-image-clone-setup.md) |
| Запись, сохранение, выбор карты и Nav2 | [Веб-навигация](web-navigation.md) |
| Именованные точки и команды «доедь до дивана» | [Точки для агента](named-places.md) |
| Чтение объектов и маркеров агентом | [Зрение агента](agent-vision.md) |
| Моторы, Device Manager, права systemd | [Обслуживание](web-hardware-setup.md) |
| Чат, MQTT-индикатор и переподключение | [Агент в вебе](web-agent.md) |
| Модели YOLO, ArUco и QR | [Зрение](vision-markers.md) |
| Экран и настройка Wi-Fi | [rover_display](../src/ui/rover_display/README.md) |
| Прошивка ESP32 и распознавание речи | [Аудиомодуль](../src/peripherals/rover_waveshare_audio/README.md) |

## Каталог ROS-пакетов

| Группа | Пакет | Назначение |
| --- | --- | --- |
| system | [rover_bringup](../src/system/rover_bringup/README.md) | Профили и композиция запусков |
| system | [rover_configuration](../src/system/rover_configuration/README.md) | Разрешение ссылок и общие launch-утилиты |
| system | [rover_description](../src/system/rover_description/README.md) | Идентичность, геометрия, URDF, RViz |
| system | [rover_interfaces](../src/system/rover_interfaces/README.md) | Сообщения, сервисы, реестр топиков |
| system | [rover_vision](../src/system/rover_vision/README.md) | YOLO и маркеры |
| motion | [rover_wheel_odometry](../src/motion/rover_wheel_odometry/README.md) | Одометрия и EKF |
| motion | [rover_navigation](../src/motion/rover_navigation/README.md) | SLAM, Nav2, библиотека карт |
| peripherals | [rover_base_driver](../src/peripherals/rover_base_driver/README.md) | Quad-MD, привод, энкодеры |
| peripherals | [rover_device_manager](../src/peripherals/rover_device_manager/README.md) | Настройка serial-устройств |
| peripherals | [rover_imu](../src/peripherals/rover_imu/README.md) | Yahboom IMU |
| peripherals | [sllidar_ros2](../src/peripherals/sllidar_ros2/README.md) | Драйвер Slamtec |
| peripherals | [rover_lidar_filter](../src/peripherals/rover_lidar_filter/README.md) | Маска корпуса в скане |
| peripherals | [rover_camera](../src/peripherals/rover_camera/README.md) | USB-видео |
| peripherals | [rover_led_strip](../src/peripherals/rover_led_strip/README.md) | Адресная LED-лента |
| peripherals | [rover_octoliner](../src/peripherals/rover_octoliner/README.md) | Датчик линии I2C |
| peripherals | [rover_waveshare_audio](../src/peripherals/rover_waveshare_audio/README.md) | Голосовой ESP32-модуль |
| agent | [rover_agent_mcp](../src/agent/rover_agent_mcp/README.md) | LLM-агент и инструменты |
| agent | [fleet_text_bridge_ros2](../src/agent/fleet_text_bridge_ros2/README.md) | MQTT-транспорт сервера |
| ui | [rover_web](../src/ui/rover_web/README.md) | Основной операторский веб |
| ui | [rover_display](../src/ui/rover_display/README.md) | Локальный сенсорный GUI |
| ui | [rosboard](../src/ui/rosboard/README.md) | Дополнительная ROS-визуализация |

## PDF и актуальность

В этой папке также находятся [полная документация в PDF](sverk_rover_full_documentation.pdf)
и [регламент](Регламент_Город_дронов_Архипелаг_2026.pdf). PDF сохранены без
редактирования и могут описывать более раннее состояние. Для текущих путей,
запусков и параметров используйте Markdown и фактические YAML/launch-файлы.
Веб-браузер документов читает `docs/`; совместимое имя параметра
`hackathon_files_root` не означает наличие старой папки.
