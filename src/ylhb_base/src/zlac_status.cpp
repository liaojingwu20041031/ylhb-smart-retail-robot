#include "ylhb_base/zlac_status.hpp"

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
  double heartbeat_timeout_sec)
{
  if (!initialized) {
    return "offline";
  }

  const bool feedback_fresh =
    feedback_seen && feedback_age_sec <= feedback_timeout_sec;
  const bool heartbeat_fresh =
    heartbeat_seen && heartbeat_age_sec <= heartbeat_timeout_sec;

  if (feedback_fresh && (!require_heartbeat || heartbeat_fresh)) {
    return "online";
  }
  if (heartbeat_fresh) {
    return "feedback_timeout";
  }
  return "stale/offline";
}

bool zlac_should_warn_cmd_timeout(
  bool motion_command_active,
  bool already_timed_out,
  double command_age_sec,
  double command_timeout_sec)
{
  return motion_command_active && !already_timed_out &&
         command_age_sec > command_timeout_sec;
}
}  // namespace ylhb_base
