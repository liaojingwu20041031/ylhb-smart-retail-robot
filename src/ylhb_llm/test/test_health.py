import time
import unittest

from ylhb_llm.health import HealthInputs, evaluate_health


class HealthTest(unittest.TestCase):
    def healthy_inputs(self):
        now = time.monotonic()
        return HealthInputs(
            now=now,
            required_nodes={
                'retail_task_node': True,
                'basic_motion_command_node': True,
                'voice_command_router_node': True,
            },
            b1_service_ready=True,
            chassis_status='online feedback_age_sec=0.1',
            chassis_received_at=now,
            voice_session_enabled=True,
            voice_session_service_ready=True,
            capture_voice_enabled=False,
            capture_voice_service_ready=False,
            tts_enabled=True,
            voice_output_present=True,
            dashscope_api_key_present=True,
            tts_speaking=False,
        )

    def test_healthy_required_chain_allows_ready(self):
        health = evaluate_health(self.healthy_inputs())
        self.assertTrue(health.ready)
        self.assertEqual(health.capabilities['capture_voice'], 'disabled')

    def test_missing_chassis_blocks_ready(self):
        inputs = self.healthy_inputs()
        inputs.chassis_status = ''
        inputs.chassis_received_at = 0.0
        health = evaluate_health(inputs)
        self.assertFalse(health.ready)
        self.assertIn('底盘状态缺失', health.reasons)

    def test_enabled_voice_requires_key_and_service(self):
        inputs = self.healthy_inputs()
        inputs.dashscope_api_key_present = False
        health = evaluate_health(inputs)
        self.assertFalse(health.ready)
        self.assertIn('ASR/TTS API Key 缺失', health.reasons)

    def test_disabled_voice_capabilities_do_not_block_ready(self):
        inputs = self.healthy_inputs()
        inputs.voice_session_enabled = False
        inputs.tts_enabled = False
        inputs.voice_session_service_ready = False
        inputs.voice_output_present = False
        inputs.dashscope_api_key_present = False
        health = evaluate_health(inputs)
        self.assertTrue(health.ready)
        self.assertEqual(health.capabilities['voice_session'], 'disabled')
        self.assertEqual(health.capabilities['tts'], 'disabled')


if __name__ == '__main__':
    unittest.main()
