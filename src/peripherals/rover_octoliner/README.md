# rover_octoliner

Драйвер Amperka Octoliner по I2C: восемь каналов, маска и положение линии.

## Запуск

```bash
ros2 launch rover_octoliner octoliner.launch.py
```

Нужны доступ к `/dev/i2c-1`, включённый I2C и Python-зависимости пакета.
[config/octoliner.yaml](config/octoliner.yaml): bus 1, адрес 42 (0x2A),
poll_rate_hz 50, sensitivity 0.8, auto_optimize_on_start false.
В full компонент выключен; включите `use_octoliner:=true` при необходимости.

## Интерфейсы

`/octoliner/reading` использует rover_interfaces/OctolinerReading.
Отдельно публикуются `/octoliner/analog`, `/octoliner/pattern`,
`/octoliner/line_position`, `/octoliner/tracked_line_position`,
`/octoliner/line_visible`, `/octoliner/sensitivity`.

Сервисы: `/octoliner/set_sensitivity` (rover_interfaces/srv/SetSensitivity),
`/octoliner/optimize_on_black` (std_srvs/srv/Trigger). Оптимизация предполагает
соответствующее реальное положение датчика над чёрной поверхностью.

Пакет только измеряет линию, не является автопилотом движения по ней.
Веб-галочка видимости панели не включает ноду. При автоматической видимости
веб проверяет наличие обработчика в ROS-графе.
