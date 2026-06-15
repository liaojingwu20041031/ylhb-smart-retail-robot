import json
import os
import time
from typing import Any, Dict, List, Tuple

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from ylhb_interfaces.msg import SayText, TaskStatus

from .product_catalog import ProductCatalog
from .voice_stability import (
    VoiceIntent,
    VoiceRoutingPolicy,
    classify_voice_intent,
    normalize_voice_text,
)


def transient_qos() -> QoSProfile:
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


class VoiceCommandRouterNode(Node):
    def __init__(self) -> None:
        super().__init__('voice_command_router_node')
        self.declare_parameter('voice_command_event_topic', '/retail_ai/voice_command_event')
        self.declare_parameter('text_command_topic', '/retail_ai/text_command')
        self.declare_parameter('system_command_topic', '/retail_ai/system_command')
        self.declare_parameter('sales_dialogue_status_topic', '/retail_ai/sales_dialogue_status')
        self.declare_parameter('system_mode_topic', '/retail_ai/system_mode')
        self.declare_parameter('task_status_topic', '/retail_ai/task_status')
        self.declare_parameter('say_text_topic', '/retail_ai/say_text')
        self.declare_parameter(
            'products_file',
            os.path.join(
                os.environ.get('WS_DIR', os.path.expanduser('~/ros2_ws')),
                'src',
                'ylhb_llm',
                'config',
                'products.yaml',
            ),
        )
        self.declare_parameter(
            'motion_aliases',
            [],
        )
        self.declare_parameter('system_commands', [])
        self.declare_parameter('voice_close_words', [])
        self.declare_parameter('safety_words', [])
        self.declare_parameter('cancel_words', [])
        self.declare_parameter('checkout_words', [])
        self.declare_parameter('system_feedback_words', [])
        self.declare_parameter('general_qa_words', [])
        self.declare_parameter('sales_need_words', [])
        self.declare_parameter('background_words', [])
        self.declare_parameter('sales_followup_words', [])
        self.declare_parameter('incomplete_motion_words', [])
        self.declare_parameter('ignore_unknown_voice', True)

        self.system_mode = 'ready'
        self.sales_status: Dict[str, Any] = {}
        self.recent_utterances = set()
        self.recent_utterance_order = []
        self.motion_aliases = self.parse_motion_aliases(
            [str(v) for v in self.get_parameter('motion_aliases').value]
        )
        self.routing_policy = self.load_routing_policy()
        self.ignore_unknown_voice = bool(
            self.get_parameter('ignore_unknown_voice').value)

        self.text_pub = self.create_publisher(String, self.get_parameter('text_command_topic').value, 10)
        self.system_command_pub = self.create_publisher(
            String, self.get_parameter('system_command_topic').value, 10)
        self.say_pub = self.create_publisher(SayText, self.get_parameter('say_text_topic').value, 10)
        self.create_subscription(
            String,
            self.get_parameter('voice_command_event_topic').value,
            self.voice_event_callback,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter('sales_dialogue_status_topic').value,
            self.sales_status_callback,
            transient_qos(),
        )
        self.create_subscription(
            String,
            self.get_parameter('system_mode_topic').value,
            self.system_mode_callback,
            transient_qos(),
        )
        self.create_subscription(
            TaskStatus,
            self.get_parameter('task_status_topic').value,
            self.task_status_callback,
            10,
        )
        self.get_logger().info('语音命令路由节点已启动。')

    def voice_event_callback(self, msg: String) -> None:
        try:
            event = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().warn(f'Invalid voice command event JSON: {exc}')
            return
        text = normalize_voice_text(str(event.get('text') or ''))
        if not text:
            return
        utterance_id = str(event.get('utterance_id') or '')
        session_id = str(event.get('session_id') or '')
        dedupe_key = f'{session_id}:{utterance_id}'
        if dedupe_key in self.recent_utterances:
            self.get_logger().info(f'Ignoring duplicate voice utterance: {dedupe_key}')
            return
        self.remember_utterance(dedupe_key)

        interaction_phase = str(event.get('interaction_phase') or 'wake_command')
        intent = self.classify(text, interaction_phase)
        if intent.route == 'ignore':
            self.get_logger().info(
                f'Ignoring non-task voice text: phase={interaction_phase}, text="{text}"'
            )
            return
        if intent.route == 'voice_close':
            self.publish_text_command(intent.text, event, 'voice_close')
            self.say(
                'voice_router',
                intent.feedback,
                priority=7,
                interrupt=True,
            )
            return
        if intent.route == 'system_command':
            self.publish_system_command(intent.system_command, intent.text, event)
            self.say(
                'voice_router',
                intent.feedback,
                priority=8,
                interrupt=intent.system_command in (
                    'emergency_stop',
                    'stop_competition_stack',
                ),
            )
            return
        if intent.route == 'unsupported_motion':
            self.say('voice_router', intent.feedback, priority=7)
            return
        if intent.route == 'global_safety':
            self.publish_text_command(intent.text, event, intent.route)
            self.say(
                'voice_router',
                intent.feedback,
                priority=8,
                interrupt=True,
            )
            return
        if intent.route == 'global_cancel':
            self.publish_text_command(intent.text, event, intent.route)
            self.say('voice_router', intent.feedback, priority=7)
            return
        if intent.route == 'task_a_motion':
            self.publish_text_command(intent.text, event, intent.route)
            return

        if self.system_mode == 'running' and intent.route in (
            'sales',
            'general_qa',
            'checkout',
        ):
            self.say('voice_router', '当前正在执行任务，请等待完成，或说取消任务。', priority=6)
            return

        self.publish_text_command(intent.text, event, intent.route)

    def classify(self, text: str, interaction_phase: str) -> VoiceIntent:
        intent = classify_voice_intent(
            text,
            policy=self.routing_policy,
            interaction_phase=interaction_phase,
            ignore_unknown_voice=self.ignore_unknown_voice,
        )
        if intent.route in ('ignore', 'sales') and interaction_phase != 'sales_followup':
            custom_motion = self.normalize_custom_motion(text)
            if custom_motion:
                return VoiceIntent('task_a_motion', custom_motion)
        return intent

    def publish_text_command(self, text: str, event: Dict[str, Any], route: str) -> None:
        command = {
            'schema_version': '1.0',
            'source': 'voice',
            'route': route,
            'session_id': str(event.get('session_id') or ''),
            'utterance_id': str(event.get('utterance_id') or ''),
            'text': text,
            'raw_asr_text': str(event.get('raw_asr_text') or text),
            'awakened': bool(event.get('awakened')),
            'contains_wake_phrase': bool(event.get('contains_wake_phrase')),
            'interaction_phase': str(
                event.get('interaction_phase') or 'wake_command'),
            'confidence': float(event.get('confidence') or 0.0),
            'timestamp': float(event.get('timestamp') or time.time()),
        }
        msg = String()
        msg.data = json.dumps(command, ensure_ascii=False)
        self.text_pub.publish(msg)
        self.get_logger().info(f'语音命令已路由到文本指令：{msg.data}')

    def publish_system_command(
        self, command: str, text: str, event: Dict[str, Any]
    ) -> None:
        payload = {
            'schema_version': '1.0',
            'source': 'voice',
            'command': command,
            'session_id': str(event.get('session_id') or ''),
            'utterance_id': str(event.get('utterance_id') or ''),
            'text': text,
            'timestamp': float(event.get('timestamp') or time.time()),
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.system_command_pub.publish(msg)
        self.get_logger().info(f'语音系统命令已发送：{msg.data}')

    def sales_status_callback(self, msg: String) -> None:
        try:
            self.sales_status = json.loads(msg.data)
        except json.JSONDecodeError:
            self.sales_status = {}

    def system_mode_callback(self, msg: String) -> None:
        mode = msg.data.strip()
        if mode:
            self.system_mode = mode

    def task_status_callback(self, msg: TaskStatus) -> None:
        if msg.status in ('completed', 'failed', 'rejected'):
            return

    def remember_utterance(self, key: str) -> None:
        self.recent_utterances.add(key)
        self.recent_utterance_order.append(key)
        while len(self.recent_utterance_order) > 100:
            old = self.recent_utterance_order.pop(0)
            self.recent_utterances.discard(old)

    def parse_motion_aliases(self, values: List[str]) -> List[Tuple[str, str]]:
        aliases: List[Tuple[str, str]] = []
        for value in values:
            alias, separator, canonical = value.partition(':')
            if separator and alias.strip() and canonical.strip():
                aliases.append((alias.strip(), canonical.strip()))
        aliases.sort(key=lambda item: len(item[0]), reverse=True)
        return aliases

    def load_routing_policy(self) -> VoiceRoutingPolicy:
        product_words: List[str] = []
        products_file = str(self.get_parameter('products_file').value)
        try:
            catalog = ProductCatalog.from_yaml(products_file)
            for product in catalog.products:
                product_words.extend([product.name, *product.aliases])
        except (OSError, KeyError, TypeError, ValueError) as exc:
            self.get_logger().warn(
                f'Failed to load voice product aliases from {products_file}: {exc}'
            )
        return VoiceRoutingPolicy(
            system_commands=self.parse_system_commands(
                self.string_list_parameter('system_commands')),
            voice_close_words=tuple(self.string_list_parameter('voice_close_words')),
            safety_words=tuple(self.string_list_parameter('safety_words')),
            cancel_words=tuple(self.string_list_parameter('cancel_words')),
            checkout_words=tuple(self.string_list_parameter('checkout_words')),
            system_feedback_words=tuple(
                self.string_list_parameter('system_feedback_words')),
            general_qa_words=tuple(self.string_list_parameter('general_qa_words')),
            sales_need_words=tuple(self.string_list_parameter('sales_need_words')),
            product_words=tuple(sorted(set(product_words), key=len, reverse=True)),
            background_words=tuple(self.string_list_parameter('background_words')),
            followup_words=tuple(
                self.string_list_parameter('sales_followup_words')),
            motion_aliases=tuple(self.motion_aliases),
            incomplete_motion_words=tuple(
                self.string_list_parameter('incomplete_motion_words')),
        )

    def string_list_parameter(self, name: str) -> List[str]:
        return [str(value) for value in self.get_parameter(name).value if str(value)]

    def parse_system_commands(
        self,
        values: List[str],
    ) -> Dict[str, Tuple[str, str]]:
        commands: Dict[str, Tuple[str, str]] = {}
        for value in values:
            parts = value.split('|', maxsplit=2)
            if len(parts) == 3 and all(part.strip() for part in parts):
                phrase, command, feedback = (part.strip() for part in parts)
                commands[phrase] = (command, feedback)
        return commands

    def normalize_custom_motion(self, text: str) -> str:
        for alias, canonical in self.motion_aliases:
            if alias == text or alias in text:
                return canonical
        return ''

    def say(
        self,
        task_id: str,
        text: str,
        priority: int = 5,
        interrupt: bool = False,
    ) -> None:
        msg = SayText()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.task_id = task_id
        msg.priority = int(priority)
        msg.interrupt = bool(interrupt)
        msg.text = text
        self.say_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceCommandRouterNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
