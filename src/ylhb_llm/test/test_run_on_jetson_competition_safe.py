import os
import unittest


class RunOnJetsonCompetitionSafeTest(unittest.TestCase):
    def test_launch_defaults_to_vl_model_for_vision(self):
        launch_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', 'launch', 'llm.launch.py')
        )
        with open(launch_path, 'r', encoding='utf-8') as handle:
            launch = handle.read()

        self.assertIn("DeclareLaunchArgument('vl_model', default_value='qwen3.7-plus')", launch)
        self.assertIn("DeclareLaunchArgument('chat_model', default_value='qwen3.7-plus')", launch)

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

    def test_competition_mode_is_safe_stack_entrypoint(self):
        script_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', '..', 'scripts', 'run_on_jetson.sh')
        )
        with open(script_path, 'r', encoding='utf-8') as handle:
            script = handle.read()

        competition_branch = script.split('competition)', 1)[1].split(';;', 1)[0]
        for required in (
            'enable_competition_executor:=true',
            'enable_vlm_shelf:=true',
            'enable_vlm_checkout:=true',
            'competition_safe_mode:=true',
            'enable_real_arm:=false',
            'skip_arm_pick_place:=true',
        ):
            self.assertIn(required, competition_branch)

    def test_docs_describe_current_safe_mode_and_route_calibration(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
        with open(os.path.join(root, 'README.md'), 'r', encoding='utf-8') as handle:
            readme = handle.read()
        with open(os.path.join(root, 'src', 'PROJECT_DOC_zh.md'), 'r', encoding='utf-8') as handle:
            project_doc = handle.read()

        self.assertIn('当前比赛保分模式', readme)
        self.assertIn('比赛前必须按实际地图标定 S/A/B 点位', readme)
        self.assertIn('增强模式', project_doc)
        self.assertIn('TTS 音频链路调试', project_doc)
        self.assertNotIn('### 任务 C 后台手动播报', project_doc)


if __name__ == '__main__':
    unittest.main()
