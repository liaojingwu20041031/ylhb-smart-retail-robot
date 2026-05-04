import os
import subprocess
import tempfile
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .qwen_client import QwenClient, QwenClientError


class VoiceInputNode(Node):
    def __init__(self) -> None:
        super().__init__('voice_input_node')
        self.declare_parameter('text_command_topic', '/retail_ai/text_command')
        self.declare_parameter('audio_device', 'default')
        self.declare_parameter('record_sec', 4.0)
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('enabled', False)
        self.declare_parameter('dashscope_base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.declare_parameter('asr_model', 'qwen3-asr-flash')
        self.declare_parameter('request_timeout_sec', 5.0)

        self.enabled = bool(self.get_parameter('enabled').value)
        self.audio_device = self.get_parameter('audio_device').value
        self.record_sec = float(self.get_parameter('record_sec').value)
        self.sample_rate = int(self.get_parameter('sample_rate').value)
        self.asr_model = self.get_parameter('asr_model').value
        self.request_timeout_sec = float(self.get_parameter('request_timeout_sec').value)
        self.qwen = QwenClient(self.get_parameter('dashscope_base_url').value)
        self.text_pub = self.create_publisher(String, self.get_parameter('text_command_topic').value, 10)
        self.stop_event = threading.Event()
        self.worker = threading.Thread(target=self.record_loop, daemon=True)
        self.worker.start()
        self.get_logger().info(f'Voice input started: enabled={self.enabled}, device={self.audio_device}')

    def record_loop(self) -> None:
        while not self.stop_event.is_set():
            if not self.enabled:
                time.sleep(1.0)
                continue
            if not self.qwen.available():
                self.get_logger().warn('DASHSCOPE_API_KEY is not set; voice input is waiting.')
                time.sleep(2.0)
                continue
            with tempfile.NamedTemporaryFile(prefix='ylhb_asr_', suffix='.wav', delete=False) as f:
                audio_path = f.name
            try:
                if not self.record_audio(audio_path):
                    time.sleep(0.5)
                    continue
                try:
                    text = self.qwen.transcribe_audio(
                        audio_path=audio_path,
                        model=self.asr_model,
                        timeout_sec=self.request_timeout_sec,
                    )
                except QwenClientError as exc:
                    self.get_logger().warn(f'ASR failed: {exc}')
                    continue
                text = text.strip()
                if text:
                    msg = String()
                    msg.data = text
                    self.text_pub.publish(msg)
                    self.get_logger().info(f'ASR command: {text}')
            finally:
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

    def record_audio(self, audio_path: str) -> bool:
        cmd = [
            'arecord',
            '-q',
            '-f', 'S16_LE',
            '-r', str(self.sample_rate),
            '-c', '1',
            '-d', str(max(1, int(round(self.record_sec)))),
        ]
        if self.audio_device and self.audio_device != 'default':
            cmd.extend(['-D', self.audio_device])
        cmd.append(audio_path)
        try:
            subprocess.run(cmd, check=True, timeout=self.record_sec + 2.0)
            return True
        except Exception as exc:
            self.get_logger().warn(f'arecord failed: {exc}')
            return False

    def destroy_node(self) -> bool:
        self.stop_event.set()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceInputNode()
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
