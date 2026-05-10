import json
import time
from typing import Optional, Tuple

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


def system_mode_qos() -> QoSProfile:
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


class BasicMotionCommandNode(Node):
    def __init__(self) -> None:
        super().__init__('basic_motion_command_node')

        self.declare_parameter('text_command_topic', '/retail_ai/text_command')
        self.declare_parameter('system_mode_topic', '/retail_ai/system_mode')
        self.declare_parameter('cmd_vel_topic', '/cmd_vel')
        self.declare_parameter('linear_speed', 0.12)
        self.declare_parameter('angular_speed', 0.45)
        self.declare_parameter('motion_duration_sec', 1.0)

        self.linear_speed = float(self.get_parameter('linear_speed').value)
        self.angular_speed = float(self.get_parameter('angular_speed').value)
        self.motion_duration_sec = float(self.get_parameter('motion_duration_sec').value)
        self.stop_at = 0.0
        self.system_mode = 'ready'

        self.cmd_pub = self.create_publisher(
            Twist, self.get_parameter('cmd_vel_topic').value, 10)
        self.create_subscription(
            String,
            self.get_parameter('text_command_topic').value,
            self.text_command_callback,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter('system_mode_topic').value,
            self.system_mode_callback,
            system_mode_qos(),
        )
        self.timer = self.create_timer(0.05, self.timer_callback)
        self.get_logger().info('Basic motion command node started.')

    def system_mode_callback(self, msg: String) -> None:
        mode = msg.data.strip()
        if mode in ('sleep', 'ready', 'mapping', 'running', 'fault'):
            self.system_mode = mode
        else:
            self.get_logger().warn(f'Ignoring unknown system_mode: {mode}')

    def text_command_callback(self, msg: String) -> None:
        text = self.command_text(msg.data)
        command = self.parse_motion_command(text)
        if command is None:
            return
        if self.system_mode in ('sleep', 'fault') and not self.is_stop_command(text):
            self.get_logger().info(
                f'Ignoring motion command while system_mode={self.system_mode}: {text}'
            )
            return

        linear_x, angular_z = command
        twist = Twist()
        twist.linear.x = linear_x
        twist.angular.z = angular_z
        self.cmd_pub.publish(twist)
        self.stop_at = time.monotonic() + self.motion_duration_sec

    def command_text(self, data: str) -> str:
        raw = data.strip()
        if not raw.startswith('{'):
            return raw
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(payload, dict):
            return str(payload.get('text') or raw).strip()
        return raw

    def timer_callback(self) -> None:
        if self.stop_at <= 0.0 or time.monotonic() < self.stop_at:
            return
        self.cmd_pub.publish(Twist())
        self.stop_at = 0.0

    def parse_motion_command(self, text: str) -> Optional[Tuple[float, float]]:
        normalized = text.strip().replace(' ', '')
        if not normalized:
            return None
        if any(token in normalized for token in ('停止', '停下', '刹车')):
            return 0.0, 0.0
        if '前进' in normalized:
            return self.linear_speed, 0.0
        if '后退' in normalized:
            return -self.linear_speed, 0.0
        if '左转' in normalized:
            return 0.0, self.angular_speed
        if '右转' in normalized:
            return 0.0, -self.angular_speed
        return None

    def is_stop_command(self, text: str) -> bool:
        normalized = text.strip().replace(' ', '')
        return any(token in normalized for token in ('停止', '停下', '刹车'))


def main(args=None) -> None:
    rclpy.init(args=args)
    node = BasicMotionCommandNode()
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
