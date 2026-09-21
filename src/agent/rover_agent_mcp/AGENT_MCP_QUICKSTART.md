# Быстрый запуск агента

Основная документация: [README](README.md). Рабочая конфигурация:
[config/agent.yaml](config/agent.yaml). Не запускайте второй агент поверх full.

```bash
cd ~/sverk_rover
source /opt/ros/jazzy/setup.bash
source install/setup.bash
# OPENAI_API_KEY должен быть уже задан в окружении, не в Git.
export OPENAI_BASE_URL='https://ai.sverk.io/v1'
export OPENAI_MODEL='qwen35'
ros2 launch rover_agent_mcp agent_mcp.launch.py
```

Для другого сервера измените URL/model. Для своей полной копии YAML:
`ros2 launch rover_agent_mcp agent_mcp.launch.py config_file:=/path/to/agent.yaml`.

Пакетный launch не объявляет llm_model/prompt_file/native_tool_mode как CLI
аргументы. Используйте YAML или OPENAI_MODEL, AGENT_PROMPT_FILE,
LLM_NATIVE_TOOL_MODE. Для systemd эти переменные задаются в
/etc/default/rover-bringup. Аппаратные ноды и MQTT-мост этот launch не запускает.

Наблюдение: `ros2 topic echo /agent/answer` и `ros2 topic echo /agent/status`.
Веб-чат и настройка внешнего сервера: [руководство](../../../docs/web-agent.md).
