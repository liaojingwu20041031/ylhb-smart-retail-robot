import os
import subprocess
import time
import unittest
from unittest.mock import patch

import rclpy
from rclpy.parameter import Parameter

from ylhb_llm.voice_command_router_node import VoiceCommandRouterNode
from ylhb_llm.voice_output_node import VoiceOutputNode
from ylhb_llm.voice_session_node import VoiceSessionNode
from ylhb_llm.voice_stability import VoiceRoutingPolicy


ARRAY_PARAMETERS = (
    'motion_aliases',
    'system_commands',
    'voice_close_words',
    'safety_words',
    'cancel_words',
    'checkout_words',
    'system_feedback_words',
    'general_qa_words',
    'sales_need_words',
    'background_words',
    'sales_followup_words',
    'incomplete_motion_words',
)


class VoiceNodeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        yaml_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'config', 'llm.yaml')
        )
        rclpy.init(args=['--ros-args', '--params-file', yaml_path])

    @classmethod
    def tearDownClass(cls):
        if rclpy.ok():
            rclpy.shutdown()

    def test_router_yaml_string_arrays_keep_string_array_type(self):
        node = VoiceCommandRouterNode()
        try:
            for name in ARRAY_PARAMETERS:
                self.assertEqual(
                    node.get_parameter(name).type_,
                    Parameter.Type.STRING_ARRAY,
                    name,
                )
        finally:
            node.destroy_node()

    def test_voice_session_yaml_arrays_keep_string_array_type(self):
        node = VoiceSessionNode()
        try:
            for name in ('wake_aliases', 'sales_followup_words', 'voice_close_words'):
                self.assertEqual(
                    node.get_parameter(name).type_,
                    Parameter.Type.STRING_ARRAY,
                    name,
                )
        finally:
            node.destroy_node()

    def test_one_wake_keeps_session_open_for_followup_commands(self):
        node = VoiceSessionNode.__new__(VoiceSessionNode)
        node.voice_close_words = ()
        node.followup_policy = VoiceRoutingPolicy()
        node.in_sales_followup = False
        node.sales_followup_until = 0.0
        node.awakened = False
        node.single_wake_default = False
        node.last_active_at = time.monotonic()
        node.wake_aliases = ['小零小零']
        node.published = []
        node.states = []
        node.update_followup_window = lambda: None
        node.set_state = node.states.append
        node.say = lambda *args, **kwargs: None
        node.publish_status = lambda: None
        node.publish_voice_event = (
            lambda text, raw, contains_wake, phase:
            node.published.append((text, contains_wake, phase))
        )

        node.handle_asr_text('小零小零你好')
        node.handle_asr_text('陪我聊一下')

        self.assertTrue(node.awakened)
        self.assertEqual([item[0] for item in node.published], ['你好', '陪我聊一下'])

    def test_sales_followup_session_publishes_product_request_without_whitelist_gate(self):
        node = VoiceSessionNode.__new__(VoiceSessionNode)
        node.voice_close_words = ()
        node.followup_policy = VoiceRoutingPolicy(followup_words=('确认',))
        node.in_sales_followup = True
        node.sales_followup_until = time.monotonic() + 5.0
        node.awakened = False
        node.single_wake_default = False
        node.last_active_at = time.monotonic()
        node.wake_aliases = ['小零小零']
        node.published = []
        node.update_followup_window = lambda: None
        node.set_state = lambda _state: None
        node.publish_voice_event = (
            lambda text, raw, contains_wake, phase:
            node.published.append((text, contains_wake, phase))
        )

        node.handle_asr_text('我想吃奥利奥')

        self.assertEqual(
            node.published,
            [('我想吃奥利奥', False, 'sales_followup')],
        )

    def test_playback_speed_uses_sox_tempo(self):
        node = VoiceOutputNode.__new__(VoiceOutputNode)
        node.playback_speed = 1.2
        node.get_logger = lambda: type(
            'Logger',
            (),
            {'warn': lambda _self, _message: None},
        )()

        completed = subprocess.CompletedProcess(args=[], returncode=0)
        with patch(
            'ylhb_llm.voice_output_node.subprocess.run',
            return_value=completed,
        ) as run:
            self.assertTrue(
                node.run_sox_tempo('/tmp/original.wav', '/tmp/faster.wav')
            )

        self.assertEqual(
            run.call_args.args[0],
            [
                'sox',
                '/tmp/original.wav',
                '/tmp/faster.wav',
                'tempo',
                '1.2',
            ],
        )

    def test_playback_speed_falls_back_to_original_when_sox_fails(self):
        node = VoiceOutputNode.__new__(VoiceOutputNode)
        node.playback_speed = 1.2
        node.run_sox_tempo = lambda _source, _target: False

        self.assertEqual(
            node.prepare_playback_audio('/tmp/original.wav'),
            '/tmp/original.wav',
        )


if __name__ == '__main__':
    unittest.main()
