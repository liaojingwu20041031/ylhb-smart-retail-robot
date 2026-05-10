import os
import queue
import subprocess
import tempfile
import threading
import time

import rclpy
from rclpy.node import Node

from ylhb_interfaces.msg import SayText, VoiceStatus

from .qwen_client import QwenClient, QwenClientError


class VoiceOutputNode(Node):
    def __init__(self) -> None:
        super().__init__('voice_output_node')
        self.declare_parameter('say_text_topic', '/retail_ai/say_text')
        self.declare_parameter('voice_status_topic', '/retail_ai/voice_status')
        self.declare_parameter('enabled', False)
        self.declare_parameter('tts_enabled', False)
        self.declare_parameter('audio_device', 'default')
        self.declare_parameter('audio_output_device', 'default')
        self.declare_parameter('dashscope_base_url', 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        self.declare_parameter('tts_model', 'qwen3-tts-flash')
        self.declare_parameter('tts_voice', 'Serena')
        self.declare_parameter('tts_language_type', 'Chinese')
        self.declare_parameter('request_timeout_sec', 5.0)
        self.declare_parameter('enable_tts_cache', True)
        self.declare_parameter('split_long_tts', True)
        self.declare_parameter('tts_segment_max_chars', 70)

        self.enabled = bool(self.get_parameter('enabled').value)
        self.tts_enabled = bool(self.get_parameter('tts_enabled').value)
        output_device = str(self.get_parameter('audio_output_device').value)
        legacy_device = str(self.get_parameter('audio_device').value)
        self.audio_device = output_device if output_device and output_device != 'default' else legacy_device
        self.tts_model = self.get_parameter('tts_model').value
        self.tts_voice = str(self.get_parameter('tts_voice').value)
        self.tts_language_type = str(self.get_parameter('tts_language_type').value)
        self.request_timeout_sec = float(self.get_parameter('request_timeout_sec').value)
        self.enable_tts_cache = bool(self.get_parameter('enable_tts_cache').value)
        self.split_long_tts = bool(self.get_parameter('split_long_tts').value)
        self.tts_segment_max_chars = int(self.get_parameter('tts_segment_max_chars').value)
        self.qwen = QwenClient(self.get_parameter('dashscope_base_url').value)
        self.queue: 'queue.PriorityQueue[tuple[int, float, SayText]]' = queue.PriorityQueue()
        self.stop_event = threading.Event()
        self.current_task_id = ''
        self.tts_cache: dict[tuple[str, str, str, str], bytes] = {}
        self.tts_cache_order: list[tuple[str, str, str, str]] = []

        self.status_pub = self.create_publisher(
            VoiceStatus, self.get_parameter('voice_status_topic').value, 10)
        self.create_subscription(
            SayText, self.get_parameter('say_text_topic').value, self.say_callback, 10)

        self.worker = threading.Thread(target=self.play_loop, daemon=True)
        self.worker.start()
        self.create_timer(0.5, self.publish_status)
        self.get_logger().info(
            f'Voice output started: enabled={self.enabled}, tts_enabled={self.tts_enabled}, '
            f'device={self.audio_device}'
        )

    def say_callback(self, msg: SayText) -> None:
        if msg.interrupt:
            self.clear_queue()
        self.queue.put((-int(msg.priority), time.time(), msg))

    def play_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                _priority, _ts, msg = self.queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self.current_task_id = msg.task_id
            text = msg.text.strip()
            if text:
                self.get_logger().info(f'SAY[{msg.task_id}]: {text}')
            if self.enabled and self.tts_enabled and text:
                segments = self.split_tts_segments(text, self.tts_segment_max_chars) if self.split_long_tts else [text]
                for segment in segments:
                    if self.stop_event.is_set():
                        break
                    self.speak(segment)
            self.current_task_id = ''
            self.queue.task_done()

    def speak(self, text: str) -> None:
        if not self.qwen.available():
            self.get_logger().warn('DASHSCOPE_API_KEY is not set; skipping TTS playback.')
            return
        cache_key = (self.tts_model, self.tts_voice, self.tts_language_type, text)
        try:
            audio = self.tts_cache.get(cache_key) if self.enable_tts_cache else None
            if audio is None:
                audio = self.qwen.synthesize_speech_bytes(
                    text=text,
                    model=self.tts_model,
                    timeout_sec=self.request_timeout_sec,
                    voice=self.tts_voice,
                    language_type=self.tts_language_type,
                )
                if audio and self.enable_tts_cache:
                    self.remember_tts_cache(cache_key, audio)
        except QwenClientError as exc:
            self.get_logger().warn(f'TTS failed: {exc}')
            return
        if not audio:
            self.get_logger().warn('TTS returned no audio; text was logged only.')
            return
        with tempfile.NamedTemporaryFile(prefix='ylhb_tts_', suffix='.wav', delete=False) as f:
            f.write(audio)
            audio_path = f.name
        try:
            cmd = ['aplay', '-q']
            if self.audio_device and self.audio_device != 'default':
                cmd.extend(['-D', self.audio_device])
            cmd.append(audio_path)
            result = subprocess.run(cmd, check=False, timeout=self.request_timeout_sec + 10.0)
            if result.returncode != 0:
                self.get_logger().warn(f'aplay failed with exit code {result.returncode}')
        except Exception as exc:
            self.get_logger().warn(f'aplay failed: {exc}')
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    def split_tts_segments(self, text: str, max_chars: int) -> list[str]:
        text = text.strip()
        if not text:
            return []
        max_chars = max(10, int(max_chars))
        raw_segments = []
        buf = ''
        for ch in text:
            buf += ch
            if ch in '。！？；;':
                raw_segments.append(buf.strip())
                buf = ''
        if buf.strip():
            raw_segments.append(buf.strip())

        merged = []
        current = ''
        for seg in raw_segments:
            if not current:
                current = seg
                continue
            if len(current) + len(seg) <= max_chars:
                current += seg
            else:
                merged.append(current)
                current = seg
        if current:
            merged.append(current)

        final_segments = []
        for seg in merged:
            while len(seg) > max_chars:
                final_segments.append(seg[:max_chars])
                seg = seg[max_chars:]
            if seg:
                final_segments.append(seg)
        return final_segments

    def remember_tts_cache(self, key: tuple[str, str, str, str], audio: bytes) -> None:
        self.tts_cache[key] = audio
        self.tts_cache_order.append(key)
        while len(self.tts_cache_order) > 64:
            old = self.tts_cache_order.pop(0)
            self.tts_cache.pop(old, None)

    def publish_status(self) -> None:
        msg = VoiceStatus()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.speaking = bool(self.current_task_id)
        msg.current_task_id = self.current_task_id
        self.status_pub.publish(msg)

    def clear_queue(self) -> None:
        while True:
            try:
                self.queue.get_nowait()
                self.queue.task_done()
            except queue.Empty:
                return

    def destroy_node(self) -> bool:
        self.stop_event.set()
        return super().destroy_node()


def main(args=None) -> None:
    rclpy.init(args=args)
    node = VoiceOutputNode()
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
