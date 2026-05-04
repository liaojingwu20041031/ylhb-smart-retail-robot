#!/bin/bash

echo "================================================="
echo "  [比赛用] 小车传感器 USB 串口别名写死锁死脚本  "
echo "================================================="

echo "- 正在写入 CP210x (激光雷达) 规则为 /dev/robot_lidar"
echo 'KERNEL=="ttyUSB*", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE:="0777", SYMLINK+="robot_lidar"' > /etc/udev/rules.d/99-robot-lidar.rules

echo "- 正在写入 CH340 (IMU) 规则为 /dev/robot_imu"
echo 'KERNEL=="ttyUSB*", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE:="0777", SYMLINK+="robot_imu"' > /etc/udev/rules.d/99-robot-imu.rules

echo "- 正在重新加载 udev 守护进程..."
service udev reload
sleep 2
udevadm trigger

echo "================================================="
echo "✅ 规则已写入！"
echo "👉 请现在把小车上的【雷达】和【IMU】的数据线全部拔下来，然后再重新插上去！"
echo "👉 然后在终端输入: ls -l /dev/robot_*"
echo "👉 如果你能看黄色字体的 /dev/robot_lidar 和 /dev/robot_imu 就代表成功了！永远不会乱了！"
echo "================================================="
