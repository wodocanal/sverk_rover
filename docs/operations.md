# Запуск и обслуживание ровера

Рабочая схема: Linux, ROS 2 Jazzy, workspace `~/sverk_rover`, пользователь
`pi`. Для другого пользователя/пути скорректируйте параметры установщика.
Все команды ниже относятся к роверу, не к macOS.

## Первый запуск

1. Подготовьте ROS/colcon/rosdep и зависимости оборудования из README пакетов.
2. Соберите workspace по [корневому README](../README.md).
3. При остановленных драйверах выполните `ros2 run rover_device_manager setup_devices`.
4. Задайте идентичность, подключение к серверу и профиль.
5. Установите сервисы и проверьте их состояние.

```bash
cd ~/sverk_rover
bash deploy/systemd/install.sh
sudo systemctl start rover-bringup
sudo systemctl start rover-web
systemctl is-enabled rover-bringup rover-web
systemctl is-active rover-bringup rover-web
```

Установщик использует `ROVER_WS`, `ROVER_SERVICE_USER`, `ROVER_SERVICE_GROUP`.
Например, для другого пользователя задайте их в окружении запуска скрипта.
Он устанавливает unit-файлы и ограниченные правила Polkit/sudoers, включает
автозагрузку, но не стартует сервисы. Существующие environment-файлы сохраняются:
проверьте `ROVER_WS` в них, если переносили workspace.

## Кто управляет процессами

| Процесс | Владелец в обычной схеме |
| --- | --- |
| Драйверы, EKF, агент, MQTT-мост | `rover-bringup.service` |
| Tkinter-экран в full | `rover-bringup.service` |
| Веб, ttyd, rosboard | `rover-web.service` |
| SLAM или Nav2, включённые кнопкой | Дочерний процесс веба внутри `rover-web.service` |

Закрытие браузера не завершает SLAM/Nav2. Перезапуск веба завершает его
навигационные процессы; сначала остановите задачу и сохраните карту.
Systemd-остановка bringup сама по себе не является координированной остановкой
всех внешних ROS-процессов. Для технического обслуживания останавливайте задачи,
затем веб и bringup. Веб-кнопки дополнительно выполняют согласованную остановку
собственных задач. Процессы, запущенные вручную, остаются ответственностью оператора.

## Настройки автозапуска

В `/etc/default/rover-bringup` задаются `ROVER_PROFILE`,
`ROVER_DISCOVERY_MODE`, `ROVER_LAUNCH_ARGS`, `ROS_DOMAIN_ID`,
`RMW_IMPLEMENTATION` и окружение агента/моста. Пример для ровера без экрана:

```ini
ROVER_PROFILE=full
ROVER_DISCOVERY_MODE=configured
ROS_DOMAIN_ID=0
ROVER_LAUNCH_ARGS="use_display:=false"
```

В `/etc/default/rover-web`: `ROVER_WEB_PORT`, `ROVER_WEB_BIND_ADDRESS`,
`ROVER_WEB_USE_ROSBOARD`, `ROVER_WEB_LAUNCH_ARGS`. Этот сервис сначала читает
окружение bringup; отдельное переопределение ROS domain в вебе может разорвать
связь с роботом. Для нескольких роверов см. [клонирование](rover-image-clone-setup.md).

Параметры `/etc/default` не загружаются в SSH-терминал автоматически.
Перед диагностикой задайте в терминале тот же `ROS_DOMAIN_ID` и RMW, что у
сервисов, и source ROS/workspace. Не публикуйте содержимое environment-файлов:
они могут содержать ключи и пароли. Изменения `.bashrc` не изменяют systemd.

## Применение изменений

| Что изменилось | Что нужно сделать |
| --- | --- |
| `/etc/default/rover-*` | Перезапустить соответствующий сервис; сборка не нужна |
| YAML в обычном install | Пересобрать пакет и перезапустить потребителя |
| Существующий YAML при symlink install | Обычно достаточно перезапуска; проверьте фактическую ссылку в install |
| Код, новые файлы, launch, package.xml, интерфейсы | Пересборка изменённых пакетов и зависимых потребителей |
| Сохранённые настройки веба | По правилам компонента: reconnect, новый запуск Nav2 или restart bringup |
| Unit-файл | Переустановка/daemon-reload и перезапуск |
| Только правила прав сервисов | Установщик прав; выполняющиеся ноды останавливать не нужно |

`systemctl start` активного сервиса не перечитывает параметры. При обновлении
веб-ресурсов также обновите страницу браузера.

## Безопасное обновление исходников

Сначала завершите движение и запись карты. Сохраните нужные карты и настройки.
Проверьте `git status --short`: локальные карты и настройки в исходниках нельзя
затирать ради обновления. Сделайте резервную копию `~/.config/rover/`,
`~/.config/sverk-rover/`, `/etc/default/rover-*` и каталога карт в защищённое
место вне Git. В копиях могут быть секреты. Это ручной процесс, автоматического
атомарного обновления с откатом в проекте пока нет.

Только после сохранения/согласования локальных изменений:

```bash
cd ~/sverk_rover
git status --short
git pull --ff-only
sudo systemctl stop rover-web
sudo systemctl stop rover-bringup
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
# Пример для workspace, который УЖЕ использует обычный install:
colcon build
```

При конфликте или расхождении Git остановитесь и сохраните обе стороны;
не используйте `reset --hard`. Если прежняя сборка использовала
`--symlink-install`, сохраните этот флаг вместо приведённого `colcon build`.
Не смешивайте режимы на одном наборе build/install и не удаляйте весь install
вслепую. Для ограниченного обновления можно использовать
`--packages-up-to <пакет>`; при смене общих интерфейсов безопаснее полная сборка.

**Только после успешной сборки**:

```bash
source install/setup.bash
# При изменениях systemd или первой установке:
bash deploy/systemd/install.sh
sudo systemctl start rover-bringup
sudo systemctl start rover-web
systemctl status rover-bringup rover-web --no-pager
```

Установщик не заменяет существующий /etc/default новыми шаблонами. Сопоставьте
его с файлами `deploy/systemd/*.env` вручную. При ошибке сборки не запускайте
частично обновлённый стек; изучите лог и восстановите согласованную версию.

## Диагностика

```bash
journalctl -u rover-bringup -n 100 --no-pager
journalctl -u rover-web -n 100 --no-pager
systemctl show rover-web -p User -p ActiveState -p MainPID
ros2 node list
ros2 topic list
ros2 topic hz /scan_filtered
ros2 topic hz /odom
```

Пустой ROS-граф при работающих сервисах часто означает другой domain/RMW или
неподключённый workspace в терминале. Активный systemd-сервис не гарантирует
исправность всех дочерних нод и свежесть датчиков.

При `Interactive authentication required` выполните на ровере:

```bash
sudo bash deploy/systemd/install-service-control.sh
```

Это устанавливает только разрешённые start/stop bringup и restart web, без
пароля в HTTP и без запуска веба от root. [Подробная диагностика прав](web-hardware-setup.md).

## Проверки изменений

После сборки и source, в изолированной ROS-среде без физических приводов:

```bash
colcon test --return-code-on-test-failure
colcon test-result --verbose
node --test src/ui/rover_web/test/*.test.cjs
```

Node.js нужен только для frontend-тестов, не для ROS-веб-сервиса. Опциональный
интеграционный тест настоящих SLAM/Nav2 включается отдельно; см.
[веб-навигацию](web-navigation.md). Тесты с искусственными данными не заменяют
проверку направления моторов, USB, питания и качества навигации на устройстве.
