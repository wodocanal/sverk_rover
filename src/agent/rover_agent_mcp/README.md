# rover_agent_mcp

Текстовый ROS-агент и локальный MCP-style JSON-RPC сервер разрешённых инструментов.
MQTT-соединением с внешним сервером занимается отдельный
[fleet_text_bridge_ros2](../fleet_text_bridge_ros2/README.md).

```text
/agent/text_command -> rover_agent_text_node -> LLM API
  -> rover_mcp_server (127.0.0.1:8766/mcp) -> ROS services/topics/actions
  -> /agent/status и /agent/answer
```

LLM использует перечисленные tools, а не произвольный shell/ROS CLI.
Движение требует отдельно запущенного оборудования, свежей одометрии и
маршрутизации /cmd_vel_test через twist_mux. Nav2-tools требуют работающего
Nav2. Инструмент `navigate_to_named_place` также может запустить Nav2 через
работающий `rover-web`, если оператор подтвердил карту и начальную позицию.
Агент сам не запускает аппаратный стек или запись карты.

## Именованные точки

`list_named_places` возвращает сохранённые названия и координаты, а
`navigate_to_named_place` отправляет выбранную точку в тот же Nav2, которым
управляет веб. По умолчанию инструмент ждёт реального результата до 90 секунд;
таймаут запрашивает отмену цели и возвращает ошибку. `get_navigation_status`
и `cancel_navigation` учитывают такую цель. Команды принимаются через ROS-сервис
`/rover/named_places` (`rover_interfaces/srv/NamedPlaces`), не через MQTT/HTTP.
Имя сервиса задаётся `mcp_server.named_places_service` в `config/agent.yaml` и
должно совпадать с `named_places_service` в конфиге веба.

См. [создание точек, подготовка старта и сценарий демо](../../../docs/named-places.md).

## Конфигурация

### Наблюдение объектов

Инструмент `observe_detections` читает `std_msgs/msg/String` с JSON из
`rover_vision`. По умолчанию он ждёт 3 новых кадра (до 8 секунд), считает класс
устойчивым при появлении хотя бы в 2 кадрах и отбрасывает оценки ниже 0.5.
Поддерживает произвольные классы модели, ArUco и QR. Старые и повторные кадры
не считаются подтверждениями; отсутствие данных отличается от пустого кадра.
Нейросеть автоматически не включается: включите обработку на странице камеры.

Топик задаётся `mcp_server.detections_topic` в `config/agent.yaml` (по умолчанию
ссылка на `/detections`) или `ROVER_DETECTIONS_TOPIC`. При смене топика детектора
обновите это значение и перезапустите MCP. Работа не зависит от открытого веба.

Примеры: «Что ты видишь?», «Есть ли перед камерой человек?»,
«Доедь до дивана и после прибытия проверь, есть ли там чашка».
Подробности параметров и ограничений: [Зрение агента](../../../docs/agent-vision.md).

### Параметры запуска

Рабочий файл: [config/agent.yaml](config/agent.yaml), секции `mcp_server` и
`text_agent`. Robot ID берётся ссылкой из rover_description; топики из
rover_interfaces. `@mcp.url` вычисляется из порта MCP. По умолчанию порт
**8766**, веб использует 8765.

Standalone launch объявляет **только `config_file`**. Произвольные аргументы
вида `llm_model:=...`, `prompt_file:=...`, `native_tool_mode:=...` не являются
поддерживаемой настройкой этого launch. Используйте рабочий YAML, свою полную
копию YAML через config_file или поддерживаемое окружение.

| Что | Переменная окружения |
| --- | --- |
| Модель и endpoint | OPENAI_MODEL, OPENAI_BASE_URL |
| API-ключ | OPENAI_API_KEY (имя задаёт llm_api_key_env / LLM_API_KEY_ENV) |
| Robot ID | FLEET_ROBOT_ID, одинаковый у агента и bridge |
| Prompt | AGENT_PROMPT_FILE |
| Native tools / planner | LLM_NATIVE_TOOL_MODE: auto, true или false |
| MCP | MCP_HOST, MCP_PORT, MCP_URL |
| Результаты детектора | ROVER_DETECTIONS_TOPIC |
| Таймаут и число раундов | LLM_TIMEOUT_SEC, LLM_MAX_TOOL_ROUNDS |

Для base URL/model есть алиасы OPENROUTER_* и SVERK_*; OPENAI_* имеют
приоритет. Ключ храните в переменной, которую реально читает llm_api_key_env.
Не путайте имя переменной с URL или самим ключом.

Для systemd окружение задаётся в /etc/default/rover-bringup, не в .bashrc.
После изменения перезапустите соответствующий сервис. Изменение Robot ID
только у одного компонента приводит к отклонению ответов мостом.

## Запуск

После сборки/source workspace, если агент ещё не запущен в full:

```bash
# OPENAI_API_KEY должен быть безопасно задан в окружении.
export OPENAI_BASE_URL='https://ai.sverk.io/v1'
export OPENAI_MODEL='qwen35'
ros2 launch rover_agent_mcp agent_mcp.launch.py
```

Это текущие дефолты проекта, не гарантия доступности конкретной модели на сервере.
Пакетный launch запускает MCP и агента вместе. Полный агентный набор без
оборудования: `ros2 launch rover_bringup robot.launch.py profile:=agent`.
Не запускайте их одновременно с тем же набором из full.

Для изолированного аппаратного запуска перед отдельным агентом отключите в
bringup `use_agent:=false use_fleet_bridge:=false` и оставьте нужные датчики/mux.
Не используйте неподдерживаемый `use_foxglove`.

## ROS-контракт

Все три топика используют std_msgs/msg/String:
`/agent/text_command`, `/agent/status`, `/agent/answer`.
Вход принимает plain text или JSON-envelope:

```json
{"message_id":"UUID","robot_id":"rover-01","text":"какие инструменты доступны?"}
```

Статусы и ответы содержат message_id и настроенный robot_id. Несовпадение ID
во входе не должно использоваться для переключения идентичности агента.
[Полный контракт](FLEET_PROTOCOL.md), [чат и сообщения сервера](../../../docs/web-agent.md).

Безопасный пример наблюдения и текстового запроса:

```bash
ros2 topic echo /agent/answer
# В другом терминале:
ros2 topic pub --once /agent/text_command std_msgs/msg/String "{data: 'как тебя зовут?'}"
```

Наличие подписчика или успешная ROS-публикация не подтверждают ответ LLM.
Успешный текстовый ответ также не гарантирует успешность каждого tool_result.

## Prompt и MCP

Дефолт: [config/default_system_prompt.md](config/default_system_prompt.md).
В config сохранены preset_*.md; меняйте стиль, не технические контракты tools.
Пример перед standalone launch:

```bash
export AGENT_PROMPT_FILE="$(ros2 pkg prefix rover_agent_mcp)/share/rover_agent_mcp/config/preset_funny.md"
export LLM_NATIVE_TOOL_MODE=false
ros2 launch rover_agent_mcp agent_mcp.launch.py
```

MCP endpoint: http://127.0.0.1:8766/mcp. Порт и bind задаются конфигом/окружением.
Не открывайте инструменты управления ровером в публичную сеть.
Для проверки перечня tools используйте реализацию
[rover_mcp_server.py](rover_agent_mcp/rover_mcp_server.py).

## Tools

### General

#### `get_available_tools()`

Возвращает категории tools и краткие описания. Используется для вопросов «что ты умеешь?».

#### `wait(duration_s)`

Ждет указанное число секунд. В sequence следующий шаг начинается сразу после окончания ожидания.

### LED strip

#### `set_led_strip(enabled, effect, brightness, color, secondary_color, effect_speed_hz)`

Низкоуровневое управление светодиодной лентой через ROS service:

```text
/led_strip/set_state
```

Эффекты:

```text
fill, blink, blink_fast, fade, wipe, flash, rainbow, rainbow_fill
```

#### `set_led_preset(preset)`

Пресеты:

```text
off, idle, zima_blue, blue, cyan, green, red, white, yellow, purple,
rainbow, thinking, navigation, manual_control, warning, blink_blue,
success, error
```

#### `blink_led_strip(color, times, interval_s, brightness, restore)`

Мигает лентой указанное число раз.

#### `get_led_strip_state()`

Возвращает последнее состояние ленты из `/led_strip/state`.

### Relative mecanum motion

Платформа считается mecanum/omni и может принимать `Twist.linear.y`, поэтому поддерживается боковое и диагональное движение.

Относительное движение использует `/odom` для проверки фактического смещения, а команды отправляет в:

```text
/cmd_vel_test
```

#### `drive_relative(forward_m, left_m, speed_mps, timeout_s)`

Odom-based движение в локальной системе робота:

```text
forward_m > 0  вперед
forward_m < 0  назад
left_m > 0     влево боком
left_m < 0     вправо боком
```

Примеры:

```json
{"forward_m": 0.30, "left_m": 0.0}
{"forward_m": 0.0, "left_m": -0.25}
{"forward_m": 0.30, "left_m": 0.30}
```

#### `turn_relative(angle_deg, angular_speed_degps, timeout_s)`

Odom-based поворот:

```text
+90 = налево
-90 = направо
```

#### `run_motion_sequence(steps, stop_on_error)`

Главный tool для сложных команд.

Поддерживаемые step types:

```text
drive_relative, drive_forward, turn_relative, navigate_to_pose,
set_led_strip, set_led_preset, blink_led_strip, wait, stop_motion
```

Если step `navigate_to_pose` находится внутри sequence, он по умолчанию ждет результат Nav2 action. Следующий шаг начинается сразу после `SUCCEEDED`/`ABORTED`/`CANCELED`, а `timeout_s` используется только как максимальная страховка.

Пример:

```json
{
  "steps": [
    {"type": "drive_relative", "forward_m": 0.30, "left_m": 0.0, "speed_mps": 0.12},
    {"type": "turn_relative", "angle_deg": -90},
    {"type": "drive_relative", "forward_m": 0.0, "left_m": 0.20, "speed_mps": 0.10},
    {"type": "blink_led_strip", "color": "#16B8F3", "times": 3}
  ],
  "stop_on_error": true
}
```

#### Compatibility aliases

```text
drive_forward(distance_m, speed_mps) -> drive_relative(forward_m=distance_m, left_m=0)
run_relative_sequence(steps) -> run_motion_sequence(steps)
```

### Nav2

#### `navigate_to_pose(x, y, yaw_deg, frame_id, wait_until_done, timeout_s)`

Отправляет абсолютную цель в Nav2 action:

```text
/navigate_to_pose
```

Если `wait_until_done=true`, tool возвращается сразу после получения action result. Если Nav2 доехал за 8 секунд, следующий шаг sequence начнется примерно через 8 секунд, а не через весь `timeout_s`.

#### `cancel_navigation()`

Отменяет текущую Nav2-цель.

#### `get_navigation_status()`

Возвращает текущий статус Nav2, последний goal, feedback и pose.

#### `is_navigation_ready()`

Проверяет доступность Nav2 action server и pose.

#### `get_robot_pose()`

Возвращает текущие координаты. Приоритет источников:

```text
/amcl_pose, затем /odom
```

### Diagnostics

#### `get_laser_summary()`

Возвращает краткую сводку по настроенному scan_topic (по умолчанию `/scan_filtered`): спереди, слева, справа, сзади.

#### `get_system_status()`

Проверяет основные интерфейсы: LED service, Nav2 action, odom, AMCL pose, scan, LED state. Battery status намеренно не включен.

## Примеры команд пользователю

```bash
ros2 topic pub --once /agent/text_command std_msgs/msg/String \
"{data: 'как тебя зовут и что ты умеешь?'}"
```

```bash
ros2 topic pub --once /agent/text_command std_msgs/msg/String \
"{data: 'на каких ты сейчас координатах?'}"
```

```bash
ros2 topic pub --once /agent/text_command std_msgs/msg/String \
"{data: 'проедь прямо 30 сантиметров, потом вправо боком 20 сантиметров и поморгай синим'}"
```

```bash
ros2 topic pub --once /agent/text_command std_msgs/msg/String \
"{data: 'езжай в точку x 1.2 y -0.4, угол 90 градусов, потом включи зеленую ленту'}"
```
