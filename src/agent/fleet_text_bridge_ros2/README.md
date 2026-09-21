# fleet_text_bridge_ros2

MQTT-мост между сервером коммуникации и ROS-агентом. Не является MCP-сервером,
не вызывает модель и не управляет моторами напрямую.

## Запуск

```bash
ros2 launch fleet_text_bridge_ros2 bridge.launch.py
# Альтернатива: мост вместе с MCP и агентом, но без оборудования:
ros2 launch fleet_text_bridge_ros2 rover_agent_stack.launch.py
```

В full и agent набор уже запускается bringup; не дублируйте его.
Рабочий конфиг существует: [config/bridge.yaml](config/bridge.yaml).
Standalone bridge.launch принимает config_file. Общий stack launch принимает
agent_config_file и bridge_config_file.

## Параметры и приоритет

robot_id ссылается на rover_description/config/rover_v1.yaml, ROS-топики на
rover_interfaces. Настройте mqtt_host/mqtt_port/mqtt_topic_prefix под свою сеть:
адрес в репозитории не является универсальным сервером.

Поддерживается окружение FLEET_ROBOT_ID, FLEET_MQTT_HOST (или FLEET_SERVER_IP),
FLEET_MQTT_PORT, FLEET_MQTT_TOPIC_PREFIX, FLEET_MQTT_USERNAME,
FLEET_MQTT_PASSWORD. Для сервиса оно задаётся в /etc/default/rover-bringup.
Окружение launch перекрывает соответствующий YAML; локальные сохранённые
параметры подключения в ~/.config/sverk-rover/fleet_connection.json имеют
приоритет над стартовыми параметрами.

Файл может содержать пароль открытым текстом, защищается правами 0600 и не
должен попадать в Git/публичный диагностический отчёт. Пустой пароль формы
сохраняет старый; явное удаление отключает fallback на окружение.

## ROS-интерфейсы

| Интерфейс | Назначение |
| --- | --- |
| /agent/text_command | Публикация проверенной команды агенту |
| /agent/status, /agent/answer | Статусы/ответы агента в MQTT |
| /fleet/connection | JSON heartbeat соединения, std_msgs/String |
| /fleet/received_command | JSON уведомление queued/sent для веба |
| /fleet_text_bridge/reconnect | std_srvs/Trigger, перечитать настройки и переподключиться |

Команды сериализуются, проверяется robot_id и защита от дубликатов message_id.
Таймаут задаётся agent_command_timeout_sec. Ответ с другим robot_id отклоняется.
Готовность MQTT учитывает подтверждения подключения/подписки/online; она не
гарантирует исправность LLM или внешнего приложения сервера.

Переподключение при активной команде или очереди отклоняется. Сохранение настроек
не равно успешному соединению. Через веб можно сохранить и переподключить
без перезапуска bringup. [Подробное руководство](../../../docs/web-agent.md).
