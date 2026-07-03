import unittest

from ylhb_llm.basic_motion_command_node import chassis_status_is_online


class MotionHealthTest(unittest.TestCase):
    def test_only_fresh_online_status_is_accepted(self):
        self.assertTrue(chassis_status_is_online('online feedback_age_sec=0.1', 0.2, 2.5))
        self.assertFalse(chassis_status_is_online('feedback_timeout', 0.2, 2.5))
        self.assertFalse(chassis_status_is_online('stale/offline', 0.2, 2.5))
        self.assertFalse(chassis_status_is_online('online', 3.0, 2.5))
        self.assertFalse(chassis_status_is_online('', 0.0, 2.5))


if __name__ == '__main__':
    unittest.main()
