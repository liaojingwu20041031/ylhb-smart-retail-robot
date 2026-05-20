# Jetson 上 PEAK PCAN-USB 的 SocketCAN 排查与安装

这份文档用于最小侵入地排查 PEAK PCAN-USB。除非已经确认 PCAN 适配器以 SocketCAN 网络接口出现，并且能看到 ZLAC8015D 的 CANopen 启动报文，否则不要修改 ROS2 功能代码，也不要修改 `src/ylhb_base/config/zlac8015d.yaml`。

## 禁止项

诊断阶段不要执行这些操作：

- 不重编译或替换 kernel `Image`。
- 不修改 `/boot/extlinux/extlinux.conf`。
- 不添加旧版 apt 源。
- 不在临时 `insmod` 验证成功、并审核安装计划前执行 `make install`。
- 如果 PCAN 只暴露为 PEAK 字符设备，不修改 ROS2 CAN 配置。

## 基线诊断

先运行仓库里的诊断脚本：

```bash
cd ~/ros2_ws
./scripts/diagnose_pcan.sh
```

重点确认这些信号：

- `lsusb` 能看到 PEAK USB 设备，例如 `0c72:000c`。
- 当前内核配置中 `CONFIG_CAN_PEAK_USB` 未启用。
- 现有 `can0` 可能是 Jetson `mttcan`，不是 PCAN-USB。
- `/lib/modules/$(uname -r)/build` 存在，说明可以编译外部驱动模块。

如果脚本因为文件缺失、grep 无匹配、`sudo dmesg` 权限等原因输出 `WARN`，这属于诊断信息，不代表脚本提前失败。

## 准备 PEAK 驱动源码

假设 `peak-linux-driver-8.15.2.tar.gz` 已经放在 `./peak-linux-driver-8.15.2.tar.gz` 或 `~/Downloads/peak-linux-driver-8.15.2.tar.gz`。只把它解压到 `~/drivers/pcan`：

```bash
mkdir -p ~/drivers/pcan
cd ~/drivers/pcan

tar -xzf ~/Downloads/peak-linux-driver-8.15.2.tar.gz
# 如果压缩包就在当前目录：
# tar -xzf ./peak-linux-driver-8.15.2.tar.gz
```

进入解压后的驱动目录：

```bash
cd ~/drivers/pcan/peak-linux-driver-8.15.2
```

编译前必须先查看构建选项：

```bash
make help || true
grep -R "NETDEV\|SOCKETCAN\|SocketCAN\|pcaninfo" -n README* Makefile driver
```

优先使用 SocketCAN/netdev 模式。先尝试：

```bash
make clean
make NET=NETDEV_SUPPORT
```

如果 README 或 Makefile 明确说明这个版本使用其他 SocketCAN/netdev 变量，则按文档中发现的选项替代。

## 只做临时加载

此时不要执行 `make install`。只从编译目录临时加载模块：

```bash
sudo insmod ./driver/pcan.ko
```

如果实际 `.ko` 路径不同，按驱动文档或编译输出中发现的路径执行。

临时加载后检查：

```bash
ip -br link
pcaninfo || true
sudo dmesg | grep -i -E "PCAN-USB|attached|peak|pcan"
```

硬门槛是 `ip -br link` 必须出现 `can1`。

如果系统只出现类似 `/sys/class/pcan/pcanusb32`，但没有 `can1`，立即停止。这说明当前是 PEAK 字符设备模式，不是 SocketCAN。不要修改 ROS2 代码，也不要修改 `zlac8015d.yaml`。

## 启动 can1 并验证 ZLAC8015D

只有 `can1` 存在时才继续：

```bash
sudo ip link set can1 down
sudo ip link set can1 type can bitrate 500000 berr-reporting on restart-ms 100
sudo ip link set can1 up
candump -tz can1
```

保持 `candump` 运行，然后给 ZLAC8015D 重新上电。必须看到启动报文：

```text
701#00
```

只有确认 `can1` 收到 `701#00` 后，才允许进入安装建议阶段。

## 安装门槛

收到 `701#00` 后，先生成并审核安装计划：

```bash
sudo make -n install | tee ~/pcan_make_install_plan.txt
```

检查 `~/pcan_make_install_plan.txt`。只有确认安装计划符合预期、只涉及目标驱动模块和相关工具后，才考虑执行：

```bash
sudo make install
```

## 回滚

如需回滚临时接口、模块或误加的自动加载配置：

```bash
sudo ip link set can1 down || true
sudo rmmod pcan || true
sudo rm -f /etc/modules-load.d/pcan.conf
sudo depmod -a
```

## ROS2 后续

只有在稳定接口最终确认为 `can1` 后，才修改 ZLAC8015D 配置：

```yaml
can_interface: can1
```

然后重新构建受影响包：

```bash
cd ~/ros2_ws
colcon build --packages-select ylhb_base
```
