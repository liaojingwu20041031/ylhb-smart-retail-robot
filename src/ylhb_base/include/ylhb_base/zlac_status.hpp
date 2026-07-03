#pragma once

#include <string>

namespace ylhb_base
{
std::string zlac_status_state(
  bool initialized,
  bool feedback_seen,
  double feedback_age_sec,
  bool heartbeat_seen,
  double heartbeat_age_sec,
  bool require_heartbeat,
  double feedback_timeout_sec,
  double heartbeat_timeout_sec);

bool zlac_should_warn_cmd_timeout(
  bool motion_command_active,
  bool already_timed_out,
  double command_age_sec,
  double command_timeout_sec);
}  // namespace ylhb_base
