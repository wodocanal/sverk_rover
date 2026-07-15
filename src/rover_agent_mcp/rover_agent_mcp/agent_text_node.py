from __future__ import annotations

import os
from pathlib import Path
import threading
import traceback
from typing import Any

import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String

from rover_agent_mcp.mcp_client import McpJsonRpcClient
from rover_agent_mcp.openrouter_host import DEFAULT_SYSTEM_PROMPT, OpenRouterHost
from rover_agent_mcp.utils import json_dumps, json_dumps_pretty


class AgentTextNode(Node):
    def __init__(self) -> None:
        super().__init__('rover_agent_text_node')

        self.declare_parameter('text_command_topic', '/agent/text_command')
        self.declare_parameter('status_topic', '/agent/status')
        self.declare_parameter('answer_topic', '/agent/answer')
        self.declare_parameter('prompt_file', '')
        self.declare_parameter('mcp_url', 'http://127.0.0.1:8765/mcp')
        self.declare_parameter('openrouter_base_url', os.getenv('OPENAI_BASE_URL', os.getenv('OPENROUTER_BASE_URL', os.getenv('SVERK_BASE_URL', 'https://openrouter.ai/api/v1'))))
        self.declare_parameter('llm_base_url', os.getenv('OPENAI_BASE_URL', os.getenv('OPENROUTER_BASE_URL', os.getenv('SVERK_BASE_URL', ''))))
        self.declare_parameter('openrouter_model', os.getenv('OPENAI_MODEL', os.getenv('OPENROUTER_MODEL', os.getenv('SVERK_MODEL', ''))))
        self.declare_parameter('llm_model', os.getenv('OPENAI_MODEL', os.getenv('OPENROUTER_MODEL', os.getenv('SVERK_MODEL', ''))))
        self.declare_parameter('openrouter_api_key_env', 'OPENROUTER_API_KEY')
        self.declare_parameter('llm_api_key_env', os.getenv('LLM_API_KEY_ENV', 'OPENAI_API_KEY'))
        self.declare_parameter('openrouter_http_referer', os.getenv('OPENROUTER_HTTP_REFERER', ''))
        self.declare_parameter('app_title', 'sverk-rover-agent')
        self.declare_parameter('timeout_s', 120.0)
        self.declare_parameter('max_tool_rounds', 8)
        self.declare_parameter('native_tool_mode', os.getenv('LLM_NATIVE_TOOL_MODE', 'auto'), descriptor=ParameterDescriptor(dynamic_typing=True))
        self.declare_parameter('publish_json_status', True)

        self.command_topic = str(self.get_parameter('text_command_topic').value)
        self.status_topic = str(self.get_parameter('status_topic').value)
        self.answer_topic = str(self.get_parameter('answer_topic').value)
        self.prompt_file = str(self.get_parameter('prompt_file').value).strip()
        self.mcp_url = str(self.get_parameter('mcp_url').value)
        self.publish_json_status = bool(self.get_parameter('publish_json_status').value)

        self._status_pub = self.create_publisher(String, self.status_topic, 10)
        self._answer_pub = self.create_publisher(String, self.answer_topic, 10)
        self.create_subscription(String, self.command_topic, self._on_text_command, 10)

        self._lock = threading.Lock()
        self._active = False

        self.get_logger().info(f'Agent listens on {self.command_topic}, publishes status to {self.status_topic} and answers to {self.answer_topic}')
        self.get_logger().info('Set OPENAI_API_KEY/OPENAI_MODEL/OPENAI_BASE_URL before sending commands. OPENROUTER_* and SVERK_* aliases are still supported.')

    def _publish_status(self, payload: str | dict[str, Any]) -> None:
        msg = String()
        if isinstance(payload, dict):
            msg.data = json_dumps(payload) if self.publish_json_status else json_dumps_pretty(payload)
        else:
            msg.data = str(payload)
        self._status_pub.publish(msg)

    def _publish_answer(self, text: str) -> None:
        msg = String()
        msg.data = str(text or '').strip()
        self._answer_pub.publish(msg)

    def _load_system_prompt(self) -> str:
        prompt_path = self.prompt_file
        if not prompt_path:
            return DEFAULT_SYSTEM_PROMPT
        try:
            path = Path(prompt_path).expanduser()
            if not path.is_file():
                self.get_logger().warning(f'prompt_file does not exist: {path}; using built-in default prompt')
                return DEFAULT_SYSTEM_PROMPT
            custom_prompt = path.read_text(encoding='utf-8').strip()
            if not custom_prompt:
                self.get_logger().warning(f'prompt_file is empty: {path}; using built-in default prompt')
                return DEFAULT_SYSTEM_PROMPT
            return DEFAULT_SYSTEM_PROMPT + '\n\n# Пользовательская кастомизация поведения\n' + custom_prompt
        except Exception as exc:
            self.get_logger().warning(f'Failed to read prompt_file {prompt_path}: {exc}; using built-in default prompt')
            return DEFAULT_SYSTEM_PROMPT


    @staticmethod
    def _mode_to_string(value: Any) -> str:
        if isinstance(value, bool):
            return 'true' if value else 'false'
        text = str(value or 'auto').strip().lower()
        if text in {'1', 'yes', 'y', 'on'}:
            return 'true'
        if text in {'0', 'no', 'n', 'off'}:
            return 'false'
        return text if text in {'auto', 'true', 'false'} else 'auto'

    def _make_host(self) -> OpenRouterHost:
        # New generic llm_* parameters are preferred. openrouter_* names are kept
        # for backward compatibility with the first version of this package.
        llm_key_env = str(self.get_parameter('llm_api_key_env').value).strip()
        openrouter_key_env = str(self.get_parameter('openrouter_api_key_env').value).strip()

        api_key = ''
        for env_name in (llm_key_env, openrouter_key_env, 'OPENAI_API_KEY', 'OPENROUTER_API_KEY', 'SVERK_API_KEY'):
            if env_name and os.getenv(env_name):
                api_key = os.getenv(env_name, '')
                break

        llm_model = str(self.get_parameter('llm_model').value).strip()
        openrouter_model = str(self.get_parameter('openrouter_model').value).strip()
        model = llm_model or openrouter_model or os.getenv('OPENAI_MODEL', '') or os.getenv('OPENROUTER_MODEL', '') or os.getenv('SVERK_MODEL', '')

        llm_base_url = str(self.get_parameter('llm_base_url').value).strip()
        openrouter_base_url = str(self.get_parameter('openrouter_base_url').value).strip()
        base_url = llm_base_url or os.getenv('OPENAI_BASE_URL', '') or os.getenv('OPENROUTER_BASE_URL', '') or os.getenv('SVERK_BASE_URL', '') or openrouter_base_url or 'https://openrouter.ai/api/v1'

        return OpenRouterHost(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_s=float(self.get_parameter('timeout_s').value),
            max_tool_rounds=int(self.get_parameter('max_tool_rounds').value),
            http_referer=str(self.get_parameter('openrouter_http_referer').value),
            app_title=str(self.get_parameter('app_title').value),
            system_prompt=self._load_system_prompt(),
            native_tool_mode=self._mode_to_string(self.get_parameter('native_tool_mode').value),
        )

    def _on_text_command(self, msg: String) -> None:
        command = str(msg.data).strip()
        if not command:
            return
        with self._lock:
            if self._active:
                self._publish_status({
                    'success': False,
                    'event': 'busy',
                    'message': 'Agent is still executing the previous command.',
                })
                return
            self._active = True
        worker = threading.Thread(target=self._run_command_thread, args=(command,), daemon=True)
        worker.start()

    def _run_command_thread(self, command: str) -> None:
        try:
            self.get_logger().info(f'Received agent command: {command}')
            self._publish_status({'event': 'received', 'command': command})
            mcp = McpJsonRpcClient(self.mcp_url, timeout_s=float(self.get_parameter('timeout_s').value))
            host = self._make_host()
            self._publish_status({
                'event': 'thinking',
                'model': host.model,
                'mcp_url': self.mcp_url,
            })
            result = host.run_command(command, mcp)
            self.get_logger().info(f'Agent result: {json_dumps(result)}')
            self._publish_status({'event': 'done', **result})
            self._publish_answer(str(result.get('reply') or 'Готово.'))
        except Exception as exc:  # pragma: no cover - runtime guard for demos
            self.get_logger().error(f'Agent command failed: {exc}\n{traceback.format_exc()}')
            self._publish_status({
                'success': False,
                'event': 'error',
                'message': str(exc),
            })
            self._publish_answer(f'Ошибка агента: {exc}')
        finally:
            with self._lock:
                self._active = False


def main() -> None:
    rclpy.init()
    node = AgentTextNode()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.remove_node(node)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
