import json
import math
import os
import threading
import time
from typing import Any, Dict, List

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String

from ylhb_interfaces.msg import SayText, TaskEvent, TaskStatus


def workspace_path(*parts: str) -> str:
    workspace_dir = os.environ.get('WS_DIR', os.path.expanduser('~/ros2_ws'))
    return os.path.join(workspace_dir, *parts)


class RetailCompetitionExecutorNode(Node):
    def __init__(self) -> None:
        super().__init__('retail_competition_executor_node')
        self.declare_parameter('task_event_topic', '/retail_ai/task_event')
        self.declare_parameter('task_status_topic', '/retail_ai/task_status')
        self.declare_parameter('say_text_topic', '/retail_ai/say_text')
        self.declare_parameter('vlm_shelf_request_topic', '/retail_ai/vlm_shelf_request')
        self.declare_parameter('vlm_checkout_request_topic', '/retail_ai/vlm_checkout_request')
        self.declare_parameter('route_file', workspace_path('maps', 'routes', 'retail_competition_route.json'))
        self.declare_parameter('competition_safe_mode', True)
        self.declare_parameter('enable_real_arm', False)
        self.declare_parameter('skip_arm_pick_place', True)
        self.declare_parameter('navigation_timeout_sec', 90.0)
        self.declare_parameter('stage_pause_sec', 0.8)
        self.declare_parameter('vlm_timeout_sec', 45.0)

        self.route_file = str(self.get_parameter('route_file').value)
        self.safe_mode = bool(self.get_parameter('competition_safe_mode').value)
        self.enable_real_arm = bool(self.get_parameter('enable_real_arm').value)
        self.skip_arm_pick_place = bool(self.get_parameter('skip_arm_pick_place').value)
        self.navigation_timeout_sec = float(self.get_parameter('navigation_timeout_sec').value)
        self.stage_pause_sec = float(self.get_parameter('stage_pause_sec').value)
        self.vlm_timeout_sec = float(self.get_parameter('vlm_timeout_sec').value)
        self.route = self.load_route(self.route_file)
        self.warn_if_placeholder_route(self.route)
        self.busy = False
        self.busy_lock = threading.Lock()
        self.vlm_condition = threading.Condition()
        self.vlm_results: Dict[tuple[str, str], str] = {}

        self.status_pub = self.create_publisher(
            TaskStatus, str(self.get_parameter('task_status_topic').value), 10)
        self.say_pub = self.create_publisher(
            SayText, str(self.get_parameter('say_text_topic').value), 10)
        self.vlm_shelf_pub = self.create_publisher(
            String, str(self.get_parameter('vlm_shelf_request_topic').value), 10)
        self.vlm_checkout_pub = self.create_publisher(
            String, str(self.get_parameter('vlm_checkout_request_topic').value), 10)
        self.create_subscription(
            TaskEvent, str(self.get_parameter('task_event_topic').value), self.task_event_callback, 10)
        self.create_subscription(
            TaskStatus, str(self.get_parameter('task_status_topic').value), self.task_status_callback, 10)
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.get_logger().info(f'Retail competition executor started. route_file={self.route_file}')

    def load_route(self, path: str) -> Dict[str, Any]:
        with open(os.path.expanduser(path), 'r', encoding='utf-8') as handle:
            return json.load(handle)

    def task_event_callback(self, msg: TaskEvent) -> None:
        intent = msg.intent
        raw = self.raw_payload(msg)
        started = False
        if intent == 'inspect_shelf_for_recommendation':
            started = self.start_workflow(msg, ['A'], inspect_shelf=True)
        elif intent == 'pick_item':
            flow = str(raw.get('flow') or '')
            if msg.source == 'image' or flow == 'task_b_1':
                started = self.start_workflow(msg, ['B'], arm=True, arm_pick_before_first_nav=True)
            else:
                started = self.start_workflow(msg, ['A', 'B', 'S'], inspect_shelf=True, arm=True)
        elif intent == 'checkout':
            started = self.start_workflow(msg, ['B'], inspect_checkout=True)
        elif intent == 'return_start':
            started = self.start_workflow(msg, ['S'], wait_if_busy=True)
        elif intent == 'retail_demo':
            started = self.start_workflow(msg, ['A', 'B', 'S'], inspect_shelf=True, inspect_checkout=True)
        if intent and not started:
            self.publish_status(msg.task_id, 'accept', 'rejected', '已有任务正在执行。')

    def start_workflow(
        self,
        event: TaskEvent,
        points: List[str],
        wait_if_busy: bool = False,
        **kwargs: Any,
    ) -> bool:
        deadline = time.monotonic() + 3.0
        while True:
            with self.busy_lock:
                if not self.busy:
                    self.busy = True
                    break
            if not wait_if_busy or time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        thread = threading.Thread(
            target=self.run_workflow,
            args=(event, points),
            kwargs=kwargs,
            daemon=True,
        )
        thread.start()
        return True

    def run_workflow(
        self,
        event: TaskEvent,
        points: List[str],
        inspect_shelf: bool = False,
        inspect_checkout: bool = False,
        arm: bool = False,
        arm_pick_before_first_nav: bool = False,
    ) -> None:
        task_id = event.task_id
        self.publish_status(task_id, 'workflow', 'started', '')
        try:
            if arm and arm_pick_before_first_nav:
                self.arm_stage(task_id, 'arm_pick')
            for point in points:
                if not self.navigate_to(point, task_id):
                    self.say(task_id, '导航失败，请检查定位或路线', priority=9)
                    self.publish_status(task_id, 'navigation', 'failed', '导航失败，请检查定位或路线')
                    return
                if point == 'A' and inspect_shelf:
                    self.clear_vlm_status(task_id, 'shelf_recognition')
                    self.publish_vlm_request(self.vlm_shelf_pub, task_id, 'arrived_shelf')
                    self.publish_status(task_id, 'shelf_recognition', 'request_sent', '')
                    if not self.wait_for_vlm_status(task_id, 'shelf_recognition'):
                        return
                    if arm and not arm_pick_before_first_nav:
                        self.arm_stage(task_id, 'arm_pick')
                if point == 'B' and inspect_checkout:
                    self.clear_vlm_status(task_id, 'checkout_inspect')
                    self.publish_vlm_request(self.vlm_checkout_pub, task_id, 'arrived_checkout')
                    self.publish_status(task_id, 'checkout_inspect', 'request_sent', '')
                    if not self.wait_for_vlm_status(task_id, 'checkout_inspect'):
                        return
                if point == 'B' and arm:
                    self.arm_stage(task_id, 'arm_place')
            if points and points[-1] == 'S':
                final_stage = 'return_start'
            elif arm:
                final_stage = 'workflow_completed'
            else:
                final_stage = 'workflow'
            self.publish_status(task_id, final_stage, 'succeeded', '')
        finally:
            with self.busy_lock:
                self.busy = False

    def raw_payload(self, msg: TaskEvent) -> Dict[str, Any]:
        try:
            value = json.loads(msg.raw_json)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    def task_status_callback(self, msg: TaskStatus) -> None:
        if msg.stage not in ('shelf_recognition', 'checkout_inspect'):
            return
        if msg.status not in ('succeeded', 'failed'):
            return
        with self.vlm_condition:
            self.vlm_results[(msg.task_id, msg.stage)] = msg.status
            self.vlm_condition.notify_all()

    def wait_for_vlm_status(self, task_id: str, stage: str) -> bool:
        deadline = time.monotonic() + self.vlm_timeout_sec
        key = (task_id, stage)
        with self.vlm_condition:
            while rclpy.ok():
                status = self.vlm_results.get(key)
                if status == 'succeeded':
                    return True
                if status == 'failed':
                    self.publish_status(task_id, stage, 'failed', 'VLM recognition failed')
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    self.publish_status(task_id, stage, 'failed', 'VLM recognition timeout')
                    return False
                self.vlm_condition.wait(timeout=min(0.2, remaining))

    def clear_vlm_status(self, task_id: str, stage: str) -> None:
        with self.vlm_condition:
            self.vlm_results.pop((task_id, stage), None)

    @staticmethod
    def is_placeholder_route(route: Dict[str, Any]) -> bool:
        targets = route.get('targets', {})
        start = route.get('start_pose', {})
        a = targets.get('A', {})
        b = targets.get('B', {})
        return (
            float(start.get('x', 999.0)) == 0.0
            and float(start.get('y', 999.0)) == 0.0
            and float(a.get('x', 999.0)) == 1.0
            and float(a.get('y', 999.0)) == 0.0
            and float(b.get('x', 999.0)) == 2.0
            and float(b.get('y', 999.0)) == 0.0
        )

    def warn_if_placeholder_route(self, route: Dict[str, Any]) -> None:
        if self.is_placeholder_route(route):
            self.get_logger().warn(
                '!!! retail_competition_route.json still uses placeholder S/A/B coordinates. '
                'Calibrate S/A/B from the actual map before competition. !!!'
            )

    def navigate_to(self, point: str, task_id: str) -> bool:
        pose = self.pose_for(point)
        self.publish_status(task_id, f'navigate_{point.lower()}', 'started', '')
        if not self.nav_client.wait_for_server(timeout_sec=5.0):
            return False
        goal = NavigateToPose.Goal()
        goal.pose = pose
        future = self.nav_client.send_goal_async(goal)
        if not self.wait_future(future, 5.0):
            return False
        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            return False
        result_future = goal_handle.get_result_async()
        if not self.wait_future(result_future, self.navigation_timeout_sec):
            goal_handle.cancel_goal_async()
            return False
        result = result_future.result()
        ok = result is not None and result.status == GoalStatus.STATUS_SUCCEEDED
        self.publish_status(task_id, f'navigate_{point.lower()}', 'succeeded' if ok else 'failed', '')
        return ok

    def wait_future(self, future: Any, timeout_sec: float) -> bool:
        deadline = time.monotonic() + timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            if future.done():
                return True
            time.sleep(0.05)
        return future.done()

    def pose_for(self, point: str) -> PoseStamped:
        key = {'S': 'start_pose', 'A': 'A', 'B': 'B'}[point]
        raw = self.route.get('start_pose') if key == 'start_pose' else self.route.get('targets', {}).get(key)
        if not isinstance(raw, dict):
            raise KeyError(f'route point missing: {point}')
        pose = PoseStamped()
        pose.header.frame_id = str(raw.get('frame_id') or 'map')
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = float(raw.get('x', 0.0))
        pose.pose.position.y = float(raw.get('y', 0.0))
        yaw = float(raw.get('yaw', 0.0))
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def arm_stage(self, task_id: str, stage: str) -> None:
        if self.safe_mode or not self.enable_real_arm or self.skip_arm_pick_place:
            self.publish_status(task_id, stage, 'succeeded', 'safe mode skipped')
            return
        self.publish_status(task_id, stage, 'failed', '真实机械臂接口尚未接入')

    def publish_vlm_request(self, publisher: Any, task_id: str, reason: str) -> None:
        msg = String()
        msg.data = json.dumps({
            'schema_version': '1.0',
            'task_id': task_id,
            'timestamp': time.time(),
            'reason': reason,
        }, ensure_ascii=False)
        publisher.publish(msg)

    def publish_status(self, task_id: str, stage: str, status: str, reason: str) -> None:
        msg = TaskStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.task_id = task_id
        msg.stage = stage
        msg.status = status
        msg.reason = reason
        self.status_pub.publish(msg)

    def say(self, task_id: str, text: str, priority: int) -> None:
        msg = SayText()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.task_id = task_id
        msg.priority = priority
        msg.text = text
        self.say_pub.publish(msg)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = RetailCompetitionExecutorNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
