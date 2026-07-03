import unittest

from ylhb_llm.retail_task_node import RetailTaskNode


class FakeQwen:
    def __init__(self, available, reply='你好，我在。'):
        self._available = available
        self.reply = reply
        self.calls = []

    def available(self):
        return self._available

    def chat_completion(self, **kwargs):
        self.calls.append(kwargs)
        return self.reply


class GeneralChatTest(unittest.TestCase):
    def make_node(self, available):
        node = RetailTaskNode.__new__(RetailTaskNode)
        node.qwen = FakeQwen(available)
        node.chat_model = 'test-chat'
        node.request_timeout_sec = 1.0
        node.general_chat_history = {}
        node.general_chat_updated_at = {}
        node.general_chat_history_timeout_sec = 35.0
        node.spoken = []
        node.say = lambda task_id, text, priority=5: node.spoken.append(text)
        return node

    def test_general_chat_without_key_uses_offline_prompt(self):
        node = self.make_node(False)
        node.handle_general_chat('task', '你好', {'session_id': 's1'})
        self.assertIn('API Key', node.spoken[-1])
        self.assertEqual(node.general_chat_history, {})

    def test_general_chat_calls_chat_model_and_keeps_six_turns(self):
        node = self.make_node(True)
        for index in range(8):
            node.handle_general_chat(
                f'task-{index}',
                f'问题{index}',
                {'session_id': 's1'},
            )
        self.assertEqual(len(node.qwen.calls), 8)
        self.assertEqual(len(node.general_chat_history['s1']), 12)
        self.assertEqual(node.spoken[-1], '你好，我在。')


if __name__ == '__main__':
    unittest.main()
