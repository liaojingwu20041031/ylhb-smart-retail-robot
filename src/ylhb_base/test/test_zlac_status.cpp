#include <gtest/gtest.h>

#include "ylhb_base/zlac_status.hpp"

using ylhb_base::zlac_status_state;
using ylhb_base::zlac_should_warn_cmd_timeout;

TEST(ZlacWatchdog, WarnsOnlyForActiveMotionCommand)
{
  EXPECT_TRUE(zlac_should_warn_cmd_timeout(true, false, 0.51, 0.5));
  EXPECT_FALSE(zlac_should_warn_cmd_timeout(false, false, 0.51, 0.5));
  EXPECT_FALSE(zlac_should_warn_cmd_timeout(true, true, 0.51, 0.5));
  EXPECT_FALSE(zlac_should_warn_cmd_timeout(true, false, 0.49, 0.5));
}

TEST(ZlacStatus, FreshFeedbackIsOnlineWithoutHeartbeatByDefault)
{
  EXPECT_EQ(
    zlac_status_state(true, true, 0.2, false, -1.0, false, 1.0, 2.0),
    "online");
}

TEST(ZlacStatus, FreshHeartbeatWithoutFeedbackReportsFeedbackTimeout)
{
  EXPECT_EQ(
    zlac_status_state(true, false, -1.0, true, 0.2, false, 1.0, 2.0),
    "feedback_timeout");
}

TEST(ZlacStatus, StaleFeedbackAndHeartbeatReportsStaleOffline)
{
  EXPECT_EQ(
    zlac_status_state(true, true, 1.2, true, 2.2, false, 1.0, 2.0),
    "stale/offline");
}

TEST(ZlacStatus, RequiredHeartbeatBlocksOnlineWhenMissing)
{
  EXPECT_NE(
    zlac_status_state(true, true, 0.2, false, -1.0, true, 1.0, 2.0),
    "online");
}

TEST(ZlacStatus, FailedInitializationIsOffline)
{
  EXPECT_EQ(
    zlac_status_state(false, true, 0.1, true, 0.1, false, 1.0, 2.0),
    "offline");
}
