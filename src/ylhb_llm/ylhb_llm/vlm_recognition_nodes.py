import json
import os
import tempfile
import time
from typing import Any, Dict, List

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from ylhb_interfaces.msg import TaskStatus

from .product_catalog import ProductCatalog
from .qwen_client import QwenClient, QwenClientError, parse_json_object


def workspace_path(*parts: str) -> str:
    workspace_dir = os.environ.get('WS_DIR', os.path.expanduser('~/ros2_ws'))
    return os.path.join(workspace_dir, *parts)


class VlmRecognitionNode(Node):
    node_name = 'vlm_recognition_node'
    default_request_topic = '/retail_ai/vlm_request'
    recognition_stage = 'vlm_recognition'
    prompt_kind = '货架'

    def __init__(self) -> None:
        super().__init__(self.node_name)
        self.declare_parameter('products_file', workspace_path('src', 'ylhb_llm', 'config', 'products.yaml'))
        self.declare_parameter('request_topic', self.default_request_topic)
        self.declare_parameter('image_topic', '/zed/zed_node/rgb/image_rect_color')
        self.declare_parameter('localized_objects_topic', '/perception/localized_objects')
        self.declare_parameter('task_status_topic', '/retail_ai/task_status')
        self.declare_parameter('dashscope_base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.declare_parameter('vl_model', 'qwen3.7-plus')
        self.declare_parameter('request_timeout_sec', 12.0)
        self.declare_parameter('max_image_age_sec', 8.0)
        self.declare_parameter('shelf_image_path', '')
        self.declare_parameter('checkout_image_path', '')

        self.catalog = ProductCatalog.from_yaml(str(self.get_parameter('products_file').value))
        self.qwen = QwenClient(str(self.get_parameter('dashscope_base_url').value))
        self.vl_model = str(self.get_parameter('vl_model').value)
        self.request_timeout_sec = float(self.get_parameter('request_timeout_sec').value)
        self.max_image_age_sec = float(self.get_parameter('max_image_age_sec').value)
        self.debug_image_path = self.selected_debug_image_path()
        self.latest_image: Image | None = None
        self.latest_image_at = 0.0

        self.localized_pub = self.create_publisher(
            String, str(self.get_parameter('localized_objects_topic').value), 10)
        self.status_pub = self.create_publisher(
            TaskStatus, str(self.get_parameter('task_status_topic').value), 10)
        self.create_subscription(
            Image, str(self.get_parameter('image_topic').value), self.image_callback, 2)
        self.create_subscription(
            String, str(self.get_parameter('request_topic').value), self.request_callback, 10)
        self.get_logger().info(
            f'{self.node_name} started. request={self.get_parameter("request_topic").value}'
        )

    def image_callback(self, msg: Image) -> None:
        self.latest_image = msg
        self.latest_image_at = time.monotonic()

    def request_callback(self, msg: String) -> None:
        payload = self.parse_request(msg.data)
        task_id = str(payload.get('task_id') or f'vlm_{int(time.time() * 1000)}')
        self.publish_status(task_id, self.recognition_stage, 'started', '')
        if not self.qwen.available():
            self.publish_status(task_id, self.recognition_stage, 'failed', 'DASHSCOPE_API_KEY 未配置。')
            return
        remove_image = False
        try:
            image_path, remove_image = self.image_path_for_request()
            objects = self.recognize_image(image_path)
        except Exception as exc:
            self.publish_status(task_id, self.recognition_stage, 'failed', f'视觉大模型识别失败：{exc}')
            return
        finally:
            if remove_image and 'image_path' in locals():
                try:
                    os.unlink(image_path)
                except OSError:
                    pass
        out = String()
        out.data = json.dumps({
            'schema_version': '1.0',
            'source': self.node_name,
            'task_id': task_id,
            'timestamp': time.time(),
            'objects': objects,
        }, ensure_ascii=False)
        self.localized_pub.publish(out)
        self.publish_status(task_id, self.recognition_stage, 'succeeded', '')

    def parse_request(self, data: str) -> Dict[str, Any]:
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def write_temp_image(self, msg: Image) -> str:
        try:
            import cv2
            from cv_bridge import CvBridge
        except ImportError as exc:
            raise RuntimeError('cv_bridge/cv2 不可用，无法读取 ZED 图像。') from exc
        frame = CvBridge().imgmsg_to_cv2(msg, desired_encoding='bgr8')
        fd, path = tempfile.mkstemp(prefix='ylhb_vlm_', suffix='.jpg')
        os.close(fd)
        if not cv2.imwrite(path, frame):
            raise RuntimeError('保存临时图像失败。')
        return path

    def recognize_image(self, image_path: str) -> List[Dict[str, Any]]:
        prompt = (
            f'你是智慧零售比赛机器人，请识别{self.prompt_kind}区域中真实可见的商品。'
            '只允许从给定商品清单里选择，不确定就不要输出。'
            '输出 JSON，不要 Markdown。字段 objects 为数组，每项包含 '
            'name, class_name, quantity, confidence, position。quantity 是同类商品数量。'
            f'商品清单：{", ".join(self.catalog.names())}。'
        )
        content = [
            {'type': 'image_url', 'image_url': {'url': self.qwen._image_data_url(image_path)}},
            {'type': 'text', 'text': prompt},
        ]
        text = self.qwen.chat_completion(
            model=self.vl_model,
            messages=[{'role': 'user', 'content': content}],
            timeout_sec=self.request_timeout_sec,
            temperature=0.0,
            extra_body={'enable_thinking': False},
        )
        parsed = parse_json_object(text)
        objects = parsed.get('objects') if isinstance(parsed.get('objects'), list) else []
        return self.filter_objects(objects)

    def filter_objects(self, objects: List[Any]) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for obj in objects:
            if not isinstance(obj, dict):
                continue
            name = ' '.join(str(obj.get(key) or '') for key in ('name', 'class_name', 'label', 'item_name'))
            product = self.catalog.match_text(name)
            if product is None:
                continue
            quantity = self.safe_quantity(obj.get('quantity'), 1)
            filtered.append({
                'name': product.name,
                'class_name': product.name,
                'item_id': product.id,
                'quantity': quantity,
                'confidence': self.safe_confidence(obj.get('confidence')),
                'position': obj.get('position') or obj.get('bbox') or '',
                'raw_name': name.strip(),
            })
        return filtered

    def safe_quantity(self, value: Any, default: int) -> int:
        try:
            quantity = int(value)
        except (TypeError, ValueError):
            quantity = default
        return max(1, quantity)

    def safe_confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError):
            confidence = 0.8
        return min(1.0, max(0.0, confidence))

    def publish_status(self, task_id: str, stage: str, status: str, reason: str) -> None:
        msg = TaskStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.task_id = task_id
        msg.stage = stage
        msg.status = status
        msg.reason = reason
        self.status_pub.publish(msg)

    def selected_debug_image_path(self) -> str:
        name = 'checkout_image_path' if self.recognition_stage == 'checkout_inspect' else 'shelf_image_path'
        return os.path.expanduser(str(self.get_parameter(name).value or ''))

    def image_path_for_request(self) -> tuple[str, bool]:
        if self.debug_image_path and os.path.isfile(self.debug_image_path):
            return self.debug_image_path, False
        if self.latest_image is None or time.monotonic() - self.latest_image_at > self.max_image_age_sec:
            raise RuntimeError('没有可用的 ZED 图像。')
        return self.write_temp_image(self.latest_image), True


class VlmShelfRecognitionNode(VlmRecognitionNode):
    node_name = 'vlm_shelf_recognition_node'
    default_request_topic = '/retail_ai/vlm_shelf_request'
    recognition_stage = 'shelf_recognition'
    prompt_kind = '货架'


class VlmCheckoutRecognitionNode(VlmRecognitionNode):
    node_name = 'vlm_checkout_recognition_node'
    default_request_topic = '/retail_ai/vlm_checkout_request'
    recognition_stage = 'checkout_inspect'
    prompt_kind = '结算'


def main_shelf(args=None) -> None:
    rclpy.init(args=args)
    node = VlmShelfRecognitionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main_checkout(args=None) -> None:
    rclpy.init(args=args)
    node = VlmCheckoutRecognitionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
