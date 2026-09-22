# rover_led_strip

Адресная LED-лента: эффекты, общее состояние и покадровое управление из ROS/веба.

## Запуск и конфиг

```bash
ros2 launch rover_led_strip led_strip.launch.py
```

Рабочий файл [config/led_strip.yaml](config/led_strip.yaml):
**42 светодиода**, led_transport auto, SPI bus 1/device 0, brightness 0.35.
В full нода запускается. enabled false задаёт исходное состояние эффекта,
но startup_self_test true выполняет световой тест при старте.

Текущий транспорт **SPI**: допустимы auto и spi. Data подключается к MOSI
фактически выбранного SPI-контроллера; проверяйте /dev/spidev* и лог ноды.
Не следуйте старой рекомендации GPIO18 для другого GPIO/NeoPixel backend.
Совместимый параметр gpio_pin не переключает текущий драйвер на этот backend.
Пользователю нужны права на SPI и Python-зависимости из package.xml.
Обеспечьте подходящее питание ленты и общую землю.

## ROS-интерфейсы

- /led_strip/state: совместимое общее состояние.
- /led_strip/set_state: rover_interfaces/srv/SetLedStripState.
- /led/state: массив состояний отдельных светодиодов.
- /led/set_effect: rover_interfaces/srv/SetLEDEffect.
- /led/set_leds: rover_interfaces/srv/SetLEDs.

Веб-страница ленты показывает состояние и позволяет задавать отдельные LED
в сетке по 7 на строку. Сами эффекты исполняются в ноде и не требуют открытого
браузера. Форматы запросов смотрите через ros2 interface show.
Не запускайте второй драйвер на ту же ленту. Для постоянных дефолтов меняйте YAML.
