# Jetson 本机化迁移备忘

这个文件只记录迁移背景和工程边界。日常使用请看：

```text
~/ros2_ws/src/PROJECT_DOC_zh.md
```

---

## 1. 迁移目标

项目现在以 Jetson Orin Nano Super 本机开发、本机构建、本机运行为准。

旧流程已经废弃：

```text
PC 端开发
PC 端做视觉识别
开发板向 PC 推流
PC 再把识别结果回传开发板
```

新流程：

```text
Jetson 本机开发
Jetson 本机构建
Jetson 本机启动 ROS 2
Jetson 本机运行 ZED 2i + YOLO26
```

---

## 2. 当前职责边界

```text
ylhb_base
  底盘、IMU、URDF、EKF、雷达、建图、导航

ylhb_perception
  ZED 图像订阅、YOLO26 检测、调试图、ZED 深度定位

zed-ros2-wrapper
  第三方 ZED 驱动，只负责相机输出

rplidar_ros-ros2
  第三方雷达驱动，只负责 /scan 输出
```

---

## 3. 关键变化

新增：

```text
scripts/install_jetson_dependencies.sh
scripts/build_on_jetson.sh
scripts/run_on_jetson.sh
src/ylhb_perception/
```

调整：

```text
src/ylhb_base/scripts/vision_node.py
```

现在它只是兼容桥，不再负责 PC 推流和 PC 回传。

导航默认地图：

```text
~/ros2_ws/src/my_map.yaml
```

---

## 4. 后续开发原则

```text
底盘和导航逻辑继续放 ylhb_base
视觉和 AI 逻辑放 ylhb_perception
不要改第三方 vendor 包来塞业务逻辑
不要再恢复 PC 推流识别流程
```

---

## 5. 最重要的推理入口

PC 端导出 ONNX，Jetson 端执行一次 ONNX 到 TensorRT engine 的本机编译。

PC 端导出 ONNX 后，把文件放到：

```text
/home/nvidia/ros2_ws/src/ylhb_perception/models/yolo26.onnx
```

Jetson 端一次性编译 TensorRT engine：

```bash
ros2 run ylhb_perception export_yolo_trt.py \
  --onnx /home/nvidia/ros2_ws/src/ylhb_perception/models/yolo26.onnx \
  --output /home/nvidia/ros2_ws/src/ylhb_perception/models/yolo26.engine \
  --workspace 2048
```

ZED + YOLO TensorRT 实时检测：

```bash
ros2 launch zed_wrapper zed_camera.launch.py camera_model:=zed2i
ros2 launch ylhb_perception perception.launch.py \
  model_path:=/home/nvidia/ros2_ws/src/ylhb_perception/models/yolo26.engine \
  backend:=tensorrt \
  imgsz:=960 \
  confidence_threshold:=0.35 \
  max_det:=20 \
  half:=true \
  publish_debug_image:=false \
  log_interval_sec:=2.0 \
  device:=cuda:0
```
