import os
import tempfile
import unittest
import wave

from ylhb_llm.product_catalog import ProductCatalog
from ylhb_llm.voice_stability import (
    VoiceRoutingPolicy,
    classify_voice_intent,
    is_sales_followup_text,
    safe_wav_duration_sec,
)


class VoiceStabilityTest(unittest.TestCase):
    def setUp(self):
        motion_aliases = (
            ('向前进', '前进'),
            ('左旋转', '左转'),
            ('前进', '前进'),
            ('停止', '停止'),
        )
        self.policy = VoiceRoutingPolicy(
            system_commands={
                '停止比赛': ('stop_competition_stack', '已发送停止比赛命令。'),
            },
            voice_close_words=('关闭语音模式',),
            safety_words=('停止', '停下', '刹车'),
            cancel_words=('取消任务', '不要了'),
            checkout_words=('结算', '付款', '多少钱', '总价'),
            general_qa_words=('你能做什么', '有什么商品'),
            sales_need_words=('我要', '口渴', '渴了'),
            product_words=('纸巾', '奥利奥'),
            background_words=('AI不出来', '差不多'),
            followup_words=('确认', '对的', '换一个', '取消', '结算'),
            motion_aliases=motion_aliases,
            incomplete_motion_words=('旋转',),
        )

    def test_motion_aliases_are_normalized(self):
        self.assertEqual(classify_voice_intent('向前进', self.policy).route, 'task_a_motion')
        self.assertEqual(classify_voice_intent('向前进', self.policy).text, '前进')
        self.assertEqual(classify_voice_intent('左旋转', self.policy).text, '左转')

    def test_incomplete_rotation_is_not_sent_to_sales(self):
        result = classify_voice_intent('旋转', self.policy)
        self.assertEqual(result.route, 'unsupported_motion')
        self.assertEqual(result.feedback, '请说左转或右转。')

    def test_background_debug_talk_is_ignored(self):
        result = classify_voice_intent('真的是AI不出来那个差不多', self.policy)
        self.assertEqual(result.route, 'ignore')

    def test_unknown_normal_talk_routes_to_general_chat(self):
        result = classify_voice_intent('你好呀陪我聊一下', self.policy)
        self.assertEqual(result.route, 'general_chat')

    def test_long_normal_talk_is_not_mistaken_for_background_debug_talk(self):
        result = classify_voice_intent('今天心情很好你愿意陪我聊聊天吗', self.policy)
        self.assertEqual(result.route, 'general_chat')

    def test_any_followup_utterance_is_sent_to_sales_semantic_model(self):
        result = classify_voice_intent(
            '今天天气不错',
            self.policy,
            interaction_phase='sales_followup',
        )
        self.assertEqual(result.route, 'sales')

    def test_product_request_in_sales_followup_routes_to_sales(self):
        result = classify_voice_intent(
            '我想吃奥利奥',
            self.policy,
            interaction_phase='sales_followup',
        )
        self.assertEqual(result.route, 'sales')

    def test_repeated_natural_confirmation_in_sales_followup_routes_to_sales(self):
        result = classify_voice_intent(
            '对的对的对的',
            self.policy,
            interaction_phase='sales_followup',
        )
        self.assertEqual(result.route, 'sales')

    def test_priority_commands_still_work_in_sales_followup(self):
        self.assertEqual(
            classify_voice_intent(
                '停止',
                self.policy,
                interaction_phase='sales_followup',
            ).route,
            'global_safety',
        )
        self.assertEqual(
            classify_voice_intent(
                '取消任务',
                self.policy,
                interaction_phase='sales_followup',
            ).route,
            'global_cancel',
        )
        self.assertEqual(
            classify_voice_intent(
                '结算',
                self.policy,
                interaction_phase='sales_followup',
            ).route,
            'checkout',
        )

    def test_explicit_sales_and_general_qa_are_allowed(self):
        self.assertEqual(classify_voice_intent('我口渴了', self.policy).route, 'sales')
        self.assertEqual(classify_voice_intent('我要纸巾', self.policy).route, 'sales')
        self.assertEqual(classify_voice_intent('你能做什么', self.policy).route, 'general_qa')
        self.assertEqual(classify_voice_intent('有什么商品', self.policy).route, 'general_qa')

    def test_product_words_can_come_from_products_yaml(self):
        with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False) as tmp:
            path = tmp.name
            tmp.write(
                'products:\n'
                '  - id: custom_item\n'
                '    name: 比赛特供\n'
                '    category: demo\n'
                '    price: 1.0\n'
                '    aliases: [特供商品]\n'
            )
        try:
            catalog = ProductCatalog.from_yaml(path)
            product_words = tuple(
                word
                for product in catalog.products
                for word in [product.name, *product.aliases]
            )
            policy = VoiceRoutingPolicy(product_words=product_words)
            self.assertEqual(classify_voice_intent('我要特供商品', policy).route, 'sales')
        finally:
            os.unlink(path)

    def test_stop_competition_has_priority_over_motion_stop(self):
        result = classify_voice_intent('停止比赛', self.policy)
        self.assertEqual(result.route, 'system_command')
        self.assertEqual(result.system_command, 'stop_competition_stack')

    def test_sales_followup_accepts_free_form_language_for_semantic_model(self):
        self.assertTrue(is_sales_followup_text('换一个', self.policy))
        self.assertTrue(is_sales_followup_text('确认', self.policy))
        self.assertTrue(is_sales_followup_text('取消', self.policy))
        self.assertTrue(is_sales_followup_text('结算', self.policy))
        self.assertTrue(is_sales_followup_text('今天天气不错', self.policy))

    def test_invalid_wav_duration_uses_file_size_estimate(self):
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            path = tmp.name
        try:
            with wave.open(path, 'wb') as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(16000)
                wav.writeframes(b'\x00\x00' * 16000)
            self.assertTrue(0.9 <= safe_wav_duration_sec(path) <= 1.1)
        finally:
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
