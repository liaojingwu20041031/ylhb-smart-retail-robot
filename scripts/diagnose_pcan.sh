#!/usr/bin/env bash
set -u

warn_count=0

section() {
  printf '\n==== %s ====\n' "$1"
}

run_cmd() {
  section "$1"
  shift
  printf '+'
  printf ' %q' "$@"
  printf '\n'

  "$@"
  local status=$?
  if [ "${status}" -ne 0 ]; then
    printf 'WARN: command exited with status %s\n' "${status}" >&2
    warn_count=$((warn_count + 1))
  fi
}

run_shell() {
  section "$1"
  shift
  printf '+ bash -c %q\n' "$1"

  bash -c "$1"
  local status=$?
  if [ "${status}" -ne 0 ]; then
    printf 'WARN: command exited with status %s\n' "${status}" >&2
    warn_count=$((warn_count + 1))
  fi
}

run_find_matches() {
  section "$1"
  shift
  printf '+'
  printf ' %q' "$@"
  printf '\n'

  local output
  output="$("$@" 2>&1)"
  local status=$?
  if [ -n "${output}" ]; then
    printf '%s\n' "${output}"
  fi
  if [ "${status}" -ne 0 ]; then
    printf 'WARN: command exited with status %s\n' "${status}" >&2
    warn_count=$((warn_count + 1))
  elif [ -z "${output}" ]; then
    printf 'WARN: no matching files found\n' >&2
    warn_count=$((warn_count + 1))
  fi
}

kernel_release="$(uname -r)"

section "PEAK PCAN-USB diagnostic"
printf 'This script only reads system state. It does not install drivers or change CAN interfaces.\n'

run_cmd "Kernel release" uname -r
run_shell "PEAK USB devices" 'lsusb | grep 0c72'
run_cmd "Network interfaces" ip -details link
run_find_matches "Kernel modules matching peak" find "/lib/modules/${kernel_release}" -iname "*peak*"
run_find_matches "Kernel modules matching pcan" find "/lib/modules/${kernel_release}" -iname "*pcan*"
run_shell "Kernel config CONFIG_CAN entries from /proc/config.gz" 'zcat /proc/config.gz | grep CONFIG_CAN'
run_shell "Kernel config CONFIG_CAN entries from /boot" "grep CONFIG_CAN /boot/config-${kernel_release}"
run_shell "Kernel log entries for CAN/PCAN/USB" 'sudo dmesg | grep -i -E "peak|pcan|can|usb"'
run_cmd "Kernel build directory" ls -ld "/lib/modules/${kernel_release}/build"

section "Summary"
if [ "${warn_count}" -eq 0 ]; then
  printf 'Completed with no command warnings.\n'
else
  printf 'Completed with %s warning(s). Review WARN sections above; missing files, no matches, and sudo denial can be expected during diagnosis.\n' "${warn_count}"
fi
