import os
import unittest

from ylhb_llm.product_catalog import ProductCatalog
from ylhb_llm.qwen_client import QwenClient
from ylhb_llm.retail_task_node import (
    RetailTaskNode,
    WAIT_CONFIRM_PRODUCT,
)


class SalesFollowupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        products_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'config', 'products.yaml')
        )
        cls.catalog = ProductCatalog.from_yaml(products_path)

    def make_node(self):
        node = RetailTaskNode.__new__(RetailTaskNode)
        node.catalog = self.catalog
        node.sales_reply_max_chars = 70
        node.sales_dialogue = {
            'active': True,
            'state': 'awaiting_confirmation',
            'waiting_for': WAIT_CONFIRM_PRODUCT,
            'pending_product_id': 'chips',
            'pending_product_name': '薯片',
            'last_product_id': 'chips',
            'last_product_name': '薯片',
            'constraints': {},
            'related_products': [],
            'history': [],
        }
        return node

    def test_local_patch_selects_mentioned_product_in_followup(self):
        node = self.make_node()

        patch = node.local_semantic_fallback_patch('我想吃奥利奥')

        self.assertIn('select_mentioned_product', node.semantic_op_names(patch))
        selected = next(
            op for op in patch['state_ops']
            if op['op'] == 'select_mentioned_product'
        )
        self.assertEqual(selected['product_id'], 'oreo')

    def test_semantic_prompt_asks_model_to_understand_free_form_confirmation(self):
        client = QwenClient.__new__(QwenClient)
        calls = []
        client.chat_completion = lambda **kwargs: calls.append(kwargs) or (
            '{"schema_version":"2.1","policy_version":"b2_state_patch_v2.1",'
            '"state_ops":[{"op":"confirm_pending_product"}],'
            '"execution":{"should_execute":true,"execute_product_id":"chips"},'
            '"context_reference":{"refers_to_pending_product":true},'
            '"utterance_properties":{},"confidence":0.9}'
        )

        client.parse_dialogue_state_patch(
            text='这就对味了，照这个来',
            model='test-model',
            timeout_sec=1.0,
            products=[{'item_id': 'chips', 'item_name': '薯片'}],
            dialogue={
                'pending_product_id': 'chips',
                'pending_product_name': '薯片',
                'waiting_for': WAIT_CONFIRM_PRODUCT,
            },
        )

        messages = calls[0]['messages']
        self.assertIn('不要依赖固定确认词表', messages[0]['content'])
        self.assertIn('这就对味了，照这个来', messages[1]['content'])
        self.assertIn('薯片', messages[1]['content'])

    def test_sales_voice_reply_is_short_and_keeps_confirmation_prompt(self):
        node = self.make_node()
        product = self.catalog.get('oreo')

        reply = node.build_sales_reply(
            need_text='有点饿，想吃点东西',
            product=product,
            alternatives=[self.catalog.get('chips')],
            reason='它是甜味饼干，适合快速补充能量',
        )

        self.assertLessEqual(len(reply), 70)
        self.assertIn('确认请说确认', reply)
        self.assertIn('换商品请直接说商品名', reply)


if __name__ == '__main__':
    unittest.main()
