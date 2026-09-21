# Sverk Rover

ROS 2 Jazzy workspace физического ровера: драйверы оборудования, одометрия и
локализация, SLAM/Nav2, веб-интерфейс, экранный GUI, компьютерное зрение,
текстовый агент и MQTT-связь с сервером. Поддерживаются меканум и обычный
дифференциальный привод. Выбор типа привода не заменяет правильную установку
колёс и калибровку моторов.

Документация описывает текущие исходники, а не гарантированное состояние
конкретного устройства. Перед первым движением поднимите колёса и проверьте
направления. Используйте веб только в доверенной сети; программный Stop не
заменяет физическое отключение моторов.

## Документация

- [Каталог руководств и всех ROS-пакетов](docs/README.md).
- [Запуск, автозагрузка, обновление и диагностика](docs/operations.md).
- [Конфиги: владельцы, ссылки и приоритеты](src/system/rover_bringup/config/README.md).
- [Настройка клонированного образа](docs/rover-image-clone-setup.md).
- [Карты и навигация из веба](docs/web-navigation.md).
- [Device Manager, моторы и сервисы](docs/web-hardware-setup.md).
- [Агент и подключение к серверу](docs/web-agent.md).
- [YOLO, ArUco и QR](docs/vision-markers.md).
- [Экран ровера](src/ui/rover_display/README.md).
- [Голосовой модуль и прошивка](src/peripherals/rover_waveshare_audio/README.md).

## Структура

```text
src/
├── agent/        # агент/MCP и MQTT-мост
├── motion/       # одометрия/EKF, навигация и карты
├── peripherals/  # моторы, камера, IMU, лидар, лента, аудио, Octoliner
├── system/       # bringup, конфигурационные утилиты, URDF, интерфейсы, vision
└── ui/           # веб, физический дисплей, rosboard
deploy/systemd/  # два сервиса и ограниченные права управления ими
docs/            # руководства и PDF
tools/           # вспомогательная настройка Wi-Fi экрана
```

Группирующие папки сами не являются ROS-пакетами. В текущем checkout нет
поддерживаемого запуска симулятора: оставшиеся каталоги кэша не означают
наличие рабочего Gazebo-окружения.

## Сборка

Команды рассчитаны на Linux с установленным ROS 2 Jazzy, rosdep и colcon.
Для новой установки из корня workspace:

```bash
cd ~/sverk_rover
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

Дополнительные аппаратные и ML-зависимости описаны в README пакетов. Для `.pt`
нужен Ultralytics в Python-окружении ноды, для экрана нужна графическая сессия
и `python3-tk`. На macOS нельзя запустить физический Linux-стек этими командами.

**Сохраняйте прежний режим сборки существующего workspace.** Если он собран
обычным `colcon build`, не добавляйте `--symlink-install` поверх существующих
артефактов. Не переключайте также `--merge-install` без отдельной миграции.
См. [процедуру обновления](docs/operations.md).

Один раз настройте последовательные устройства при остановленных драйверах:

```bash
ros2 run rover_device_manager setup_devices
```

Мастер сохраняет назначение Quad-MD, IMU и лидара в
`~/.config/rover/devices.json`. После каждого обновления повторять его не нужно.
Веб-вариант находится в **Настройки -> Device Manager**.

## Обычный запуск через systemd

После успешной сборки:

```bash
cd ~/sverk_rover
bash deploy/systemd/install.sh
sudo systemctl start rover-bringup
sudo systemctl start rover-web
systemctl is-enabled rover-bringup rover-web
systemctl is-active rover-bringup rover-web
```

Установщик включает автозагрузку, но не запускает сервисы сам. Существующие
`/etc/default/rover-*` сохраняются. Пользователь по умолчанию `pi`.

| Сервис | Что запускает |
| --- | --- |
| `rover-bringup` | Профиль робота без веба и rosboard; физический экран остаётся в `full` |
| `rover-web` | Веб, веб-терминал и по умолчанию rosboard; без физического экрана |

Веб: `http://<IP-ровера>:8765/`. Rosboard по умолчанию использует порт 8888,
MCP слушает `127.0.0.1:8766`. Не выставляйте интерфейсы в публичную сеть.

Профиль и исключения задаются в `/etc/default/rover-bringup`:

```ini
ROVER_PROFILE=full
ROVER_DISCOVERY_MODE=configured
ROS_DOMAIN_ID=0
ROVER_LAUNCH_ARGS="use_display:=false"
```

Порт, bind-адрес и rosboard задаются в `/etc/default/rover-web`. Веб также читает
окружение bringup, поэтому ROS domain обычно общий. После правки используйте
`restart`: `start` работающего сервиса ничего не перечитывает. `.bashrc` не
является источником окружения systemd.

## Профили и отдельные launch

Главный launch называется **`robot.launch.py`**, не `rover.launch.py`.
Не запускайте его поверх работающего `rover-bringup`.

```bash
ros2 launch rover_bringup robot.launch.py profile:=full
ros2 launch rover_bringup robot.launch.py profile:=full use_camera:=false use_vision:=false
ros2 launch rover_camera camera.launch.py
```

| Профиль | Состав |
| --- | --- |
| `full` | База, одометрия/EKF, описание, IMU, лидар, камера/vision, лента, twist_mux, UI, агент и bridge |
| `hardware` | База, одометрия/EKF, описание, IMU, лидар, камера/vision; без UI и агента |
| `minimal` | База, одометрия, описание, EKF без IMU |
| `mapping` | Оборудование для картографии, веб и SLAM |
| `navigation` | Оборудование, камера/vision, веб, twist_mux и Nav2 |
| `agent` | MCP, текстовый агент и MQTT-мост без драйверов |

`ui.yaml` является конфигом отдельного `ui.launch.py`, а не аппаратным профилем
для `robot.launch.py`. В `full` выключены Nav2, SLAM, Octoliner и голосовой
модуль. Нода vision запускается, но обработка по `vision.yaml` выключена до
нажатия кнопки в вебе. Флаги состава не равнозначны активности обработки.

У компонентов есть собственные launch-файлы и YAML. Bringup подключает их,
передавая найденные устройства и общие параметры. Не допускайте двух процессов,
владеющих одной камерой, serial-портом или одинаковым ROS-интерфейсом.

## Карты и навигация

Обычный сценарий: сервисы с `full`, затем **Движение -> Визуализация**.
SLAM запускается по кнопке записи карты; Nav2 после выбора карты, initial pose,
цели и нажатия запуска. Переключение режима не перезапускает оборудование.
Закрытие вкладки не останавливает задачу; **перезапуск `rover-web` останавливает
управляемые им SLAM/Nav2**. Отдельных systemd-сервисов для них пока нет.

Сохраняйте карту до остановки SLAM. CLI-эквивалент:

```bash
ros2 run rover_navigation rover_map save room
ros2 run rover_navigation rover_map list
ros2 run rover_navigation rover_map status
```

По умолчанию карты находятся в `src/motion/rover_navigation/maps/current`, архив
рядом в `maps/archive`; `ROVER_MAPS_ROOT` позволяет выбрать другой корень.
Выбор архивной карты в вебе не заменяет `current`. Для продолжения картографии
нужны `.posegraph` и `.data`, одной occupancy-карты недостаточно.
CLI-запуски описаны в [rover_navigation](src/motion/rover_navigation/README.md).

## Где изменять параметры

Параметры устройств принадлежат пакетам; bringup хранит состав запуска в
`config/profiles`. Идентичность/геометрия находятся в
`rover_description/config/rover_v1.yaml`, общие имена в
`rover_interfaces/config/topics.yaml`. Ссылки `package://` разрешает
`rover_configuration`, а не сам `ros2 run --params-file`.

Сохранённые в вебе тип привода, калибровка моторов, настройки навигации и
MQTT-подключение находятся в `~/.config/sverk-rover/`. Они могут перекрывать
YAML пакета. Изменения camera/vision через ROS-параметры не следует считать
постоянными: для следующего запуска правьте рабочий YAML. `*.example.yaml`
не загружаются вместо рабочего конфига автоматически.

Агент/MCP читают `rover_agent_mcp/config/agent.yaml`, MQTT-мост читает
`fleet_text_bridge_ros2/config/bridge.yaml`. Ключ модели задаётся через
`OPENAI_API_KEY` в окружении процесса, для сервиса через `/etc/default/rover-bringup`.
Секреты не коммитятся. [Подробности приоритетов](src/system/rover_bringup/config/README.md).

Руководства и PDF находятся в `docs/`; веб читает их оттуда. Старое имя параметра
`hackathon_files_root` сохранено, его значение теперь `~/sverk_rover/docs`.
Обновите ручные переопределения старого пути.

## Лицензия

Собственный код проекта: [MIT License](LICENSE), Copyright (c) 2026 Sverk.
Сторонние компоненты, модели и документы сохраняют свои лицензии и уведомления.
Лицензия корня не перелицензирует ROSboard, Slamtec SDK или веса YOLO;
для модели см. [описание моделей](src/system/rover_vision/models/README.md).
