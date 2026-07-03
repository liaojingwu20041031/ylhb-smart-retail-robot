import os
import unittest


class RunOnJetsonCompetitionSafeTest(unittest.TestCase):
    def test_competition_safe_mode_launches_safe_vlm_executor_stack(self):
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts', 'run_on_jetson.sh')
        )
        with open(script_path, 'r', encoding='utf-8') as handle:
            script = handle.read()

        self.assertIn('competition_safe)', script)
        for required in (
            'enable_competition_executor:=true',
            'enable_vlm_shelf:=true',
            'enable_vlm_checkout:=true',
            'competition_safe_mode:=true',
            'enable_real_arm:=false',
            'skip_arm_pick_place:=true',
            'enable_voice:=true',
            'enable_tts:=true',
            'route_file:="${WS_DIR}/maps/routes/retail_competition_route.json"',
        ):
            self.assertIn(required, script)


if __name__ == '__main__':
    unittest.main()
