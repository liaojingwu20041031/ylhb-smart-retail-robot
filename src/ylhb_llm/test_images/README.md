# 大模型本地图片测试目录

把任务书图片放在这个目录下，例如：

```text
/home/nvidia/ros2_ws/src/ylhb_llm/test_images/task_b.png
```

启动大模型任务层：

```bash
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
export DASHSCOPE_API_KEY="你的真实DashScope_API_Key"
ros2 launch ylhb_llm llm.launch.py enable_voice:=false enable_tts:=false
```

目录内只保留一张 `.jpg/.jpeg/.png` 任务书图片，然后启动 B-1：

```bash
ros2 service call /retail_ai/start_b1_task std_srvs/srv/Trigger "{}"
```

查看播报文本：

```bash
ros2 topic echo /retail_ai/say_text --once
```

图片理解播报的预期风格是 2 到 3 个短句：先说明画面中可见的人物、表情、动作或思考气泡，再自然推断需求。例如“这张图像展示了一个看起来口渴的卡通男孩。他的舌头伸出，思考气泡中有一杯水，暗示他想要喝水。”不要让模型只输出一句夸张结论。

测试文字购物和本地价格计算：

```bash
ros2 topic pub --once /retail_ai/text_command std_msgs/msg/String "{data: '来瓶可乐'}"
ros2 topic echo /retail_ai/task_event --once
```

把上一步输出里的 `task_id` 填到下面，模拟导航/抓取成功：

```bash
ros2 topic pub --once /retail_ai/task_status ylhb_interfaces/msg/TaskStatus \
  "{task_id: '替换成实际task_id', stage: 'place', status: 'succeeded', reason: ''}"
```

再测试结算：

```bash
ros2 topic pub --once /retail_ai/text_command std_msgs/msg/String "{data: '一共多少钱'}"
ros2 topic echo /retail_ai/cart --once
ros2 topic echo /retail_ai/say_text --once
```
