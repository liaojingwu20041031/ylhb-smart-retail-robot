#!/usr/bin/env bash
set -euo pipefail

tarball="${HOME}/Downloads/peak-linux-driver-8.15.2.tar.gz"
base_dir="${HOME}/drivers/pcan"
driver_dir="${base_dir}/peak-linux-driver-8.15.2"
netdev_confirmed=0
selected_can_iface=""
module_paths=()

usage() {
  cat <<'USAGE'
Usage: scripts/install_peak_pcan_safe.sh [--precheck|--build|--test-load|--install|--rollback]

安全边界:
  - 默认不安装，不修改 /boot，不修改 kernel/initrd，不修改 ROS2 功能代码。
  - 只自动接受 SocketCAN/netdev 编译方式: NET=NETDEV_SUPPORT。
  - 不添加 apt 源，不安装 pcanview，不自动运行 candump。

阶段:
  --precheck   解压或复用驱动源码，检查环境并确认 NET=NETDEV_SUPPORT 是否存在
  --build      先执行 precheck，确认 SocketCAN/netdev 后编译并查找 .ko
  --test-load  先执行 build，临时加载模块，检测 canX，并配置 500k
  --install    先执行 test-load，打印 make install 计划，输入精确 YES 后安装
  --rollback   只 down can1/can2、卸载 pcan、删除 /etc/modules-load.d/pcan.conf、depmod
USAGE
}

section() {
  printf '\n==== %s ====\n' "$1"
}

die() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

run() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  "$@"
}

warn_run() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  "$@" || printf 'WARN: command failed, continuing\n' >&2
}

ensure_driver_source() {
  mkdir -p "${base_dir}"

  if [ -d "${driver_dir}" ]; then
    printf 'Reusing existing driver directory: %s\n' "${driver_dir}"
    return
  fi

  if [ ! -f "${tarball}" ]; then
    die "未找到驱动压缩包: ${tarball}"
  fi

  section "Extract driver tarball"
  run tar -xzf "${tarball}" -C "${base_dir}"

  if [ ! -d "${driver_dir}" ]; then
    die "解压后未找到目标目录: ${driver_dir}"
  fi
}

grep_driver_netdev_hints() {
  local grep_paths=()

  shopt -s nullglob
  grep_paths+=("${driver_dir}"/README*)
  shopt -u nullglob

  if [ -e "${driver_dir}/Makefile" ]; then
    grep_paths+=("${driver_dir}/Makefile")
  fi
  if [ -d "${driver_dir}/driver" ]; then
    grep_paths+=("${driver_dir}/driver")
  fi

  if [ "${#grep_paths[@]}" -eq 0 ]; then
    printf 'WARN: no README*, Makefile, or driver path found under %s\n' "${driver_dir}" >&2
    return 1
  fi

  grep -R "NETDEV\|SOCKETCAN\|SocketCAN\|pcaninfo\|PCAN-Basic\|NO_NETDEV\|NET=" -n "${grep_paths[@]}"
}

precheck() {
  section "Precheck"
  ensure_driver_source

  section "Kernel release"
  run uname -r

  section "PEAK USB devices"
  if command -v lsusb >/dev/null 2>&1; then
    if ! lsusb | grep 0c72; then
      printf 'WARN: 未发现 USB vendor id 0c72 的 PEAK 设备，继续检查源码和内核环境。\n' >&2
    fi
  else
    printf 'WARN: lsusb 不存在，跳过 PEAK USB 设备检查。\n' >&2
  fi

  section "Kernel build directory"
  local kernel_release
  kernel_release="$(uname -r)"
  run test -d "/lib/modules/${kernel_release}/build"
  run ls -ld "/lib/modules/${kernel_release}/build"

  section "Driver make help"
  (cd "${driver_dir}" && make help) || true

  section "Driver SocketCAN/netdev hints"
  local grep_output
  grep_output="$(grep_driver_netdev_hints 2>&1 || true)"
  if [ -n "${grep_output}" ]; then
    printf '%s\n' "${grep_output}"
  else
    printf 'WARN: 未找到 SocketCAN/netdev 相关提示。\n' >&2
  fi

  if printf '%s\n' "${grep_output}" | grep -q "NET=NETDEV_SUPPORT"; then
    netdev_confirmed=1
    printf '\n已确认 SocketCAN/netdev 编译方式: NET=NETDEV_SUPPORT\n'
  else
    netdev_confirmed=0
    printf '\n未确认 SocketCAN 编译方式，不自动编译\n'
  fi
}

build_driver() {
  precheck

  if [ "${netdev_confirmed}" -ne 1 ]; then
    die "未确认 SocketCAN 编译方式，不自动编译"
  fi

  section "Build PEAK PCAN SocketCAN/netdev driver"
  (cd "${driver_dir}" && run make clean)
  (cd "${driver_dir}" && run make NET=NETDEV_SUPPORT)

  section "Built kernel modules"
  mapfile -t module_paths < <(cd "${driver_dir}" && find . -name "*.ko" -print)
  if [ "${#module_paths[@]}" -eq 0 ]; then
    die "编译完成但未找到 .ko 模块"
  fi
  printf '%s\n' "${module_paths[@]}"
}

list_can_ifaces() {
  ip -br link | awk '$1 ~ /^can[0-9]+(@.*)?$/ { sub(/@.*/, "", $1); print $1 }'
}

choose_can_iface() {
  local before_file="$1"
  local after_file="$2"
  local new_iface=""
  local fallback_iface=""

  while IFS= read -r iface; do
    if ! grep -Fxq "${iface}" "${before_file}"; then
      new_iface="${iface}"
      break
    fi
  done < "${after_file}"

  if [ -n "${new_iface}" ]; then
    selected_can_iface="${new_iface}"
    return 0
  fi

  while IFS= read -r iface; do
    if [ "${iface}" != "can0" ]; then
      fallback_iface="${iface}"
      break
    fi
  done < "${after_file}"

  if [ -n "${fallback_iface}" ]; then
    selected_can_iface="${fallback_iface}"
    return 0
  fi

  return 1
}

detect_char_device_without_netdev() {
  local pcaninfo_output="$1"

  if printf '%s\n' "${pcaninfo_output}" | grep -qi "pcanusb32"; then
    return 0
  fi

  if find /sys -iname "*pcanusb32*" -print -quit 2>/dev/null | grep -q .; then
    return 0
  fi

  return 1
}

test_load() {
  build_driver

  section "Existing CAN interfaces"
  local before_file
  local after_file
  before_file="$(mktemp)"
  after_file="$(mktemp)"
  trap 'rm -f "${before_file}" "${after_file}"' RETURN

  list_can_ifaces | tee "${before_file}"

  section "Load CAN dependencies"
  warn_run sudo modprobe can
  warn_run sudo modprobe can_raw
  warn_run sudo modprobe can_dev

  section "Temporary insmod built modules"
  local module_path
  for module_path in "${module_paths[@]}"; do
    if ! (cd "${driver_dir}" && run sudo insmod "${module_path}"); then
      printf 'WARN: insmod %s 失败；如果模块已加载，将继续检查接口状态。\n' "${module_path}" >&2
    fi
  done

  printf '\n请拔插 PEAK PCAN-USB，然后按 Enter 继续...'
  read -r _

  section "CAN interfaces after load"
  ip -br link
  list_can_ifaces | tee "${after_file}"

  section "pcaninfo"
  local pcaninfo_output
  pcaninfo_output="$(pcaninfo 2>&1 || true)"
  if [ -n "${pcaninfo_output}" ]; then
    printf '%s\n' "${pcaninfo_output}"
  else
    printf 'pcaninfo 未输出或命令不存在。\n'
  fi

  section "Kernel log"
  sudo dmesg | grep -i -E "pcan|peak|can|usb|attached" || true

  if ! choose_can_iface "${before_file}" "${after_file}"; then
    if detect_char_device_without_netdev "${pcaninfo_output}"; then
      die "当前不是 SocketCAN/netdev 模式，ROS2 不能直接使用"
    fi
    die "未发现可用 canX 接口"
  fi

  section "Configure ${selected_can_iface} at 500k"
  warn_run sudo ip link set "${selected_can_iface}" down
  run sudo ip link set "${selected_can_iface}" type can bitrate 500000 berr-reporting on restart-ms 100
  run sudo ip link set "${selected_can_iface}" up
  run ip -details link show "${selected_can_iface}"

  printf '\n不自动运行 candump。需要观察时请执行:\n'
  printf '  candump -tz %s\n' "${selected_can_iface}"
  printf '给 ZLAC8015D 重新上电，观察是否收到 701#00。\n'
  printf '只有确认 %s 能收到 ZLAC8015D 的 701#00 后，才把 zlac8015d.yaml 里的 can_interface 从 can0 改为 %s。\n' "${selected_can_iface}" "${selected_can_iface}"
}

install_driver() {
  test_load

  if [ -z "${selected_can_iface}" ]; then
    die "未确认可用 canX，不执行安装"
  fi

  section "make install dry-run plan"
  (cd "${driver_dir}" && sudo make -n install | tee "${HOME}/pcan_make_install_plan.txt")

  printf '\n安装计划已写入: %s\n' "${HOME}/pcan_make_install_plan.txt"
  printf '只有确认上方计划安全时，输入精确 YES 才执行 sudo make install: '
  local answer
  read -r answer
  if [ "${answer}" != "YES" ]; then
    printf '未输入 YES，退出，不安装。\n'
    return 0
  fi

  section "Install driver"
  (cd "${driver_dir}" && run sudo make install)

  printf '\n只有确认 %s 能收到 ZLAC8015D 的 701#00 后，才把 zlac8015d.yaml 里的 can_interface 从 can0 改为 %s。\n' "${selected_can_iface}" "${selected_can_iface}"
}

rollback() {
  section "Rollback non-critical PCAN changes"
  printf '+ sudo ip link set can1 down 2>/dev/null || true\n'
  sudo ip link set can1 down 2>/dev/null || true
  printf '+ sudo ip link set can2 down 2>/dev/null || true\n'
  sudo ip link set can2 down 2>/dev/null || true
  printf '+ sudo rmmod pcan 2>/dev/null || true\n'
  sudo rmmod pcan 2>/dev/null || true
  printf '+ sudo rm -f /etc/modules-load.d/pcan.conf\n'
  sudo rm -f /etc/modules-load.d/pcan.conf
  run sudo depmod -a
}

case "${1:-}" in
  --precheck)
    precheck
    ;;
  --build)
    build_driver
    ;;
  --test-load)
    test_load
    ;;
  --install)
    install_driver
    ;;
  --rollback)
    rollback
    ;;
  "")
    usage
    exit 1
    ;;
  -h|--help)
    usage
    ;;
  *)
    usage >&2
    die "未知参数: $1"
    ;;
esac
