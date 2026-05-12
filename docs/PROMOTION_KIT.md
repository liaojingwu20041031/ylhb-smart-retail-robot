# YLHB Smart Retail Robot 传播素材包

这个文档用于把项目包装成更容易被看到、被 Star、被转发的开源机器人项目。可以直接复制到 GitHub About、B 站、知乎、公众号、朋友圈、比赛汇报或简历项目经历中。

---

## 1. GitHub About 推荐设置

### Description

```text
ROS 2 + Jetson Orin Nano Super 多模态智慧零售机器人：Nav2 导航、ZED 2i 视觉、YOLO/TensorRT 商品识别、Qwen 大模型任务理解、连续语音交互与比赛 UI 总控台。
```

### Website

如果暂时没有项目主页，可以先留空。后续建议放：

```text
B 站演示视频链接 / 项目介绍文章链接 / GitHub Pages 链接
```

### Topics

```text
ros2
jetson
nav2
slam
robotics
smart-retail
zed-camera
yolo
tensorrt
llm
qwen
dashscope
voice-assistant
pyqt
competition-robot
```

---

## 2. 一句话介绍

### 中文版

```text
一个基于 ROS 2 和 Jetson Orin Nano Super 的多模态智慧零售机器人项目，完整打通建图导航、视觉识别、大模型任务理解、连续语音交互和比赛 UI 总控台。
```

### 更有传播感的版本

```text
我做了一台会听、会看、会推荐、会自己去货架取商品的 ROS 2 智慧零售机器人。
```

### 英文版

```text
A ROS 2 and Jetson-powered multimodal smart retail robot with Nav2 navigation, ZED 2i perception, YOLO/TensorRT object detection, Qwen-based task understanding, continuous voice interaction, and a competition-ready UI console.
```

---

## 3. 适合放在 README / 简历 / 项目展示里的介绍

```text
YLHB Smart Retail Robot 是一个面向智慧零售比赛场景的 ROS 2 机器人系统，部署在 Jetson Orin Nano Super 上，集成 RPLidar、ZED 2i、STM32 底盘、IMU、YOLO/TensorRT、Nav2、SLAM Toolbox、DashScope/Qwen 大模型和 PyQt 比赛 UI。

项目支持文字和语音任务输入，能够完成商品需求理解、销售式推荐、用户确认、导航到货架、商品识别、结算播报和返回起点等流程。仓库以完整 ROS 2 工作区形式组织，包含底盘控制、感知、AI 任务层、自定义消息、启动脚本和比赛现场调试文档。
```

---

## 4. B 站 / 抖音 / 视频号标题

### 技术向

1. `我把 ROS 2、Jetson、ZED、YOLO 和大模型接成了一台智慧零售机器人`
2. `Jetson Orin Nano Super 跑 ROS 2 智慧零售机器人：会听会看还会推荐商品`
3. `从 Nav2 到大模型语音交互：我的 ROS 2 比赛机器人完整系统`
4. `机器人比赛项目实战：ROS 2 + YOLO + Qwen 多模态任务理解`
5. `一台能听懂“我口渴了”的智能零售机器人是怎么做出来的？`

### 更吸引路人的版本

1. `我做了一台会自己去货架拿饮料的机器人`
2. `对机器人说“我口渴了”，它真的会去推荐并拿商品`
3. `大学生做的 AI 零售机器人：语音下单、视觉识别、自动导航`
4. `把大模型塞进机器人后，它开始像销售员一样推荐商品`
5. `这不是 PPT，这是我真跑起来的 ROS 2 智慧零售机器人`

---

## 5. 视频脚本：30 秒短视频版

```text
【0-3s】开场：展示机器人和 UI
字幕：我做了一台 ROS 2 智慧零售机器人。

【3-8s】语音唤醒
人声：小零小零，我口渴了。
字幕：连续语音识别 + 大模型任务理解。

【8-13s】AI 推荐
机器人播报：推荐可乐，也可以选择矿泉水或果汁。
字幕：大模型根据需求进行销售式推荐。

【13-18s】用户确认
人声：确认。
字幕：用户确认后才触发取货任务。

【18-24s】导航与识别
画面：Nav2 导航、ZED 画面、YOLO 检测框。
字幕：RPLidar 建图导航 + ZED 2i + YOLO/TensorRT 商品识别。

【24-30s】结算和收尾
画面：UI 显示购物车、总价、任务状态。
字幕：完整打通语音、视觉、导航、大模型和比赛 UI。GitHub 已开源。
```

---

## 6. 视频脚本：2 分钟技术讲解版

```text
大家好，这是我做的 YLHB Smart Retail Robot，一个基于 ROS 2 和 Jetson Orin Nano Super 的智慧零售机器人项目。

它不是单独的视觉 demo，也不是单独的导航 demo，而是一个完整比赛流程系统。底层使用 STM32 底盘、RPLidar、IMU 和 robot_localization 做运动与位姿融合；导航层使用 SLAM Toolbox、AMCL 和 Nav2；视觉层使用 ZED 2i 采集 RGB 与深度信息，再通过 YOLO26 和 TensorRT 做商品检测；AI 层接入 DashScope/Qwen，负责图片任务理解、文字命令理解、语音 ASR、TTS 播报和销售对话。

在 B-2 场景中，用户可以直接说“我口渴了”。系统不会立刻机械地取货，而是先像销售员一样推荐商品，比如推荐可乐、矿泉水或果汁。只有用户说“确认”之后，系统才会发布结构化任务事件，导航到货架区 A，识别商品，执行取货，然后到结算区 B，最后返回起点。

我还做了比赛显示屏 UI，可以统一展示任务入口、节点状态、识别结果、购物车、总价和语音播报内容。现场只需要运行 competition 启动模式，就可以通过 UI 一键拉起比赛节点。

这个项目已经整理成完整 ROS 2 工作区并开源，包含启动脚本、部署说明、调试文档和安全规范。后续我会继续补充演示视频、系统截图和更完整的英文文档。
```

---

## 7. 知乎 / 公众号文章标题

1. `我如何用 ROS 2 + Jetson 做出一台多模态智慧零售机器人`
2. `从底盘到大模型：一个大学生 ROS 2 比赛机器人项目复盘`
3. `智能零售机器人系统设计：Nav2、YOLO、ZED、Qwen 与 PyQt 总控台`
4. `把大模型接进机器人比赛系统后，我踩过的坑和解决方案`
5. `ROS 2 项目工程化实践：从能跑的 demo 到能比赛的系统`

---

## 8. 平台标签

### B 站标签

```text
ROS2, Jetson, 机器人, 智能车, 大模型, YOLO, Nav2, SLAM, 计算机专业, 大学生项目, 嵌入式AI
```

### GitHub Topics

```text
ros2, robotics, jetson, nav2, slam, smart-retail, zed-camera, yolo, tensorrt, llm, qwen, dashscope, voice-assistant, pyqt, competition-robot
```

### 知乎关键词

```text
ROS2 机器人、Jetson Orin Nano、Nav2 导航、机器人比赛、大模型 Agent、YOLO 商品识别、多模态机器人、嵌入式 AI
```

---

## 9. 推荐补充的演示素材

为了让项目看起来更像成熟开源项目，建议补齐这些素材：

| 优先级 | 素材 | 文件名建议 | 说明 |
|---|---|---|---|
| 高 | 30 秒总览 GIF | `docs/assets/demo-overview.gif` | 放在 README 首屏，最能提高 Star 转化 |
| 高 | UI 截图 | `docs/assets/ui-dashboard.png` | 展示完成度和比赛总控台 |
| 高 | 商品识别截图 | `docs/assets/yolo-detection.png` | 展示视觉能力 |
| 中 | Nav2 导航动图 | `docs/assets/nav2-demo.gif` | 展示机器人真实运行 |
| 中 | 语音交互视频 | `docs/assets/voice-demo.mp4` | 展示“我口渴了 -> 推荐 -> 确认 -> 取货”流程 |
| 中 | 系统架构图 PNG | `docs/assets/architecture.png` | 给不能渲染 Mermaid 的平台使用 |
| 低 | 硬件接线图 | `docs/assets/hardware-wiring.png` | 方便别人复现 |

---

## 10. Star 转化建议

1. README 首屏尽量先放演示 GIF，再放技术栈，不要一上来就是长命令。
2. GitHub About 必须填 description 和 topics，否则搜索曝光会弱很多。
3. B 站视频简介第一行放 GitHub 链接，评论区置顶 GitHub 链接。
4. README 里保留“适合谁参考”，让 ROS 2 / Jetson / 比赛机器人用户知道这个项目对他们有用。
5. 每次解决一个明显问题后发 release 或短动态，例如“连续语音模式稳定性优化”“Jetson 本机化迁移完成”。
6. 不要只展示代码，重点展示“机器人真的跑起来了”。机器人项目最强传播素材永远是运行视频。

---

## 11. 简历项目经历写法

```text
YLHB Smart Retail Robot｜ROS 2 多模态智慧零售机器人
- 基于 Jetson Orin Nano Super、ROS 2 Humble、RPLidar、ZED 2i、STM32 底盘和 IMU 搭建比赛级移动机器人系统。
- 使用 SLAM Toolbox、AMCL、Nav2 和 robot_localization 实现建图、定位、路径规划、避障和位姿融合。
- 基于 YOLO26、TensorRT、ZED RGB-D 数据实现商品检测和视觉感知链路。
- 接入 DashScope/Qwen 实现任务书图片理解、自然语言商品需求解析、销售式推荐、ASR/TTS 和连续语音会话。
- 开发 PyQt 比赛显示屏 UI 与 system supervisor，统一管理任务 A/B/C/D、节点启动、识别结果、购物车和结算状态。
```

---

## 12. 后续可以做的包装升级

- 增加英文 README：扩大海外 ROS/Jetson 用户可见度。
- 增加 GitHub Actions：只检查自研包格式和基础测试，不把第三方 vendor 包作为质量门槛。
- 增加 `docs/assets/` 演示素材：README 首屏放 GIF。
- 增加 `docs/ARCHITECTURE.md`：把节点图、topic/service、任务流拆开讲。
- 增加 `docs/TROUBLESHOOTING.md`：整理 Jetson、ZED、RPLidar、音频设备、DashScope 常见问题。
- 增加 Release：例如 `v0.1.0-competition-ready`，让项目更像正式工程。
