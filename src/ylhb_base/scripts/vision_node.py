#!/usr/bin/env python3

import rclpy
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from std_msgs.msg import String


class LegacyVisionBridge(Node):
    """
    Deprecated compatibility bridge for old /vision topics.

    The active Jetson-native perception pipeline lives in ylhb_perception.
    This node only republishes its outputs to the legacy topic names that
    older state-machine code may still consume.
    """

    def __init__(self) -> None:
        super().__init__('legacy_vision_bridge')

        self.declare_parameter('source_detections_topic', '/perception/detections')
        self.declare_parameter('legacy_result_topic', '/vision/result')
        self.declare_parameter('source_target_pose_topic', '/perception/target_pose')
        self.declare_parameter('legacy_target_pose_topic', '/vision/target_pose')

        source_detections_topic = self.get_parameter('source_detections_topic').value
        legacy_result_topic = self.get_parameter('legacy_result_topic').value
        source_target_pose_topic = self.get_parameter('source_target_pose_topic').value
        legacy_target_pose_topic = self.get_parameter('legacy_target_pose_topic').value

        self.result_pub = self.create_publisher(String, legacy_result_topic, 10)
        self.target_pose_pub = self.create_publisher(PoseStamped, legacy_target_pose_topic, 10)

        self.create_subscription(String, source_detections_topic, self.result_callback, 10)
        self.create_subscription(PoseStamped, source_target_pose_topic, self.pose_callback, 10)

        self.get_logger().warn(
            "ylhb_base/scripts/vision_node.py is deprecated. "
            "Start Jetson-native perception with: "
            "ros2 launch ylhb_perception perception.launch.py"
        )
        self.get_logger().info(
            f"Republishing {source_detections_topic} -> {legacy_result_topic}, "
            f"{source_target_pose_topic} -> {legacy_target_pose_topic}"
        )

    def result_callback(self, msg: String) -> None:
        self.result_pub.publish(msg)

    def pose_callback(self, msg: PoseStamped) -> None:
        self.target_pose_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LegacyVisionBridge()
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
