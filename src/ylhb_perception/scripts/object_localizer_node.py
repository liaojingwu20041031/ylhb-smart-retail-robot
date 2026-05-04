#!/usr/bin/env python3

import json
from typing import Any, Dict, List, Optional

import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import PoseStamped
from rclpy.node import Node
from sensor_msgs.msg import CameraInfo, Image
from std_msgs.msg import String


class ObjectLocalizerNode(Node):
    def __init__(self) -> None:
        super().__init__('object_localizer_node')

        self.declare_parameter('detections_topic', '/perception/detections')
        self.declare_parameter('depth_topic', '/zed/zed_node/depth/depth_registered')
        self.declare_parameter('camera_info_topic', '/zed/zed_node/rgb/color/rect/camera_info')
        self.declare_parameter('target_pose_topic', '/perception/target_pose')
        self.declare_parameter('localized_objects_topic', '/perception/localized_objects')
        self.declare_parameter('camera_frame', 'zed_left_camera_frame_optical')
        self.declare_parameter('max_depth_m', 8.0)
        self.declare_parameter('min_depth_m', 0.2)

        self.detections_topic = self.get_parameter('detections_topic').value
        self.depth_topic = self.get_parameter('depth_topic').value
        self.camera_info_topic = self.get_parameter('camera_info_topic').value
        self.target_pose_topic = self.get_parameter('target_pose_topic').value
        self.localized_objects_topic = self.get_parameter('localized_objects_topic').value
        self.camera_frame = self.get_parameter('camera_frame').value
        self.max_depth_m = float(self.get_parameter('max_depth_m').value)
        self.min_depth_m = float(self.get_parameter('min_depth_m').value)

        self.bridge = CvBridge()
        self.last_depth: Optional[np.ndarray] = None
        self.last_camera_info: Optional[CameraInfo] = None

        self.target_pose_pub = self.create_publisher(PoseStamped, self.target_pose_topic, 1)
        self.localized_objects_pub = self.create_publisher(String, self.localized_objects_topic, 1)

        self.create_subscription(Image, self.depth_topic, self.depth_callback, 1)
        self.create_subscription(CameraInfo, self.camera_info_topic, self.camera_info_callback, 1)
        self.create_subscription(String, self.detections_topic, self.detections_callback, 1)

        self.get_logger().info(
            f"Object localizer started: detections={self.detections_topic}, "
            f"depth={self.depth_topic}, camera_info={self.camera_info_topic}"
        )

    def depth_callback(self, msg: Image) -> None:
        try:
            depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')
        except Exception as exc:
            self.get_logger().warn(f"Failed to convert depth image: {exc}")
            return

        depth = np.asarray(depth)
        if msg.encoding in ('16UC1', 'mono16'):
            depth = depth.astype(np.float32) * 0.001
        else:
            depth = depth.astype(np.float32)
        self.last_depth = depth

    def camera_info_callback(self, msg: CameraInfo) -> None:
        self.last_camera_info = msg

    def detections_callback(self, msg: String) -> None:
        if self.last_depth is None or self.last_camera_info is None:
            return

        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().warn(f"Invalid detections JSON: {exc}")
            return

        localized: List[Dict[str, Any]] = []
        for detection in payload.get('detections', []):
            item = self._localize_detection(detection)
            if item is not None:
                localized.append(item)

        out_payload = {
            'header': payload.get('header', {}),
            'frame_id': self.camera_frame,
            'objects': localized,
        }

        out = String()
        out.data = json.dumps(out_payload, ensure_ascii=True)
        self.localized_objects_pub.publish(out)

        if localized:
            self._publish_target_pose(localized[0], payload.get('header', {}))

    def _localize_detection(self, detection: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        bbox = detection.get('bbox_xyxy')
        if not bbox or len(bbox) != 4:
            return None

        depth = self.last_depth
        info = self.last_camera_info
        if depth is None or info is None:
            return None

        x1, y1, x2, y2 = [int(round(v)) for v in bbox]
        h, w = depth.shape[:2]
        cx = int(round((x1 + x2) * 0.5))
        cy = int(round((y1 + y2) * 0.5))
        cx = int(np.clip(cx, 0, w - 1))
        cy = int(np.clip(cy, 0, h - 1))

        radius = 3
        x_min = max(0, cx - radius)
        x_max = min(w, cx + radius + 1)
        y_min = max(0, cy - radius)
        y_max = min(h, cy + radius + 1)
        patch = depth[y_min:y_max, x_min:x_max]
        valid = patch[np.isfinite(patch)]
        valid = valid[(valid >= self.min_depth_m) & (valid <= self.max_depth_m)]
        if valid.size == 0:
            return None

        z = float(np.median(valid))
        fx = float(info.k[0])
        fy = float(info.k[4])
        ox = float(info.k[2])
        oy = float(info.k[5])
        if fx == 0.0 or fy == 0.0:
            return None

        x = (float(cx) - ox) * z / fx
        y = (float(cy) - oy) * z / fy

        result = dict(detection)
        result['position_camera_frame'] = {'x': x, 'y': y, 'z': z}
        result['frame_id'] = self.camera_frame
        return result

    def _publish_target_pose(self, obj: Dict[str, Any], header: Dict[str, Any]) -> None:
        pos = obj.get('position_camera_frame', {})
        pose = PoseStamped()
        stamp = header.get('stamp', {})
        pose.header.stamp.sec = int(stamp.get('sec', 0))
        pose.header.stamp.nanosec = int(stamp.get('nanosec', 0))
        pose.header.frame_id = self.camera_frame
        pose.pose.position.x = float(pos.get('x', 0.0))
        pose.pose.position.y = float(pos.get('y', 0.0))
        pose.pose.position.z = float(pos.get('z', 0.0))
        pose.pose.orientation.w = 1.0
        self.target_pose_pub.publish(pose)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = ObjectLocalizerNode()
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
