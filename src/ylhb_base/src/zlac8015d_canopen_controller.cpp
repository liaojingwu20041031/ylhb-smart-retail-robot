#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <std_msgs/msg/string.hpp>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <tf2_ros/transform_broadcaster.h>

#include <linux/can.h>
#include <linux/can/raw.h>
#include <net/if.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <unistd.h>

#include <algorithm>
#include <array>
#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <limits>
#include <optional>
#include <sstream>
#include <string>

using namespace std::chrono_literals;

namespace
{
constexpr uint16_t kControlWord = 0x6040;
constexpr uint16_t kStatusWord = 0x6041;
constexpr uint16_t kModesOfOperation = 0x6060;
constexpr uint16_t kActualVelocity = 0x606C;
constexpr uint16_t kTargetVelocity = 0x60FF;
constexpr uint16_t kProfileAcceleration = 0x6083;
constexpr uint16_t kProfileDeceleration = 0x6084;
constexpr uint16_t kFaultCode = 0x603F;
constexpr uint16_t kVendorControlMode = 0x200F;

template <typename T>
T clamp_value(T value, T min_value, T max_value)
{
  return std::max(min_value, std::min(value, max_value));
}

std::string frame_to_string(const can_frame & frame)
{
  std::ostringstream out;
  out << std::hex << std::uppercase << std::setfill('0') << std::setw(3) << frame.can_id << "#";
  for (int i = 0; i < frame.can_dlc; ++i) {
    out << std::setw(2) << static_cast<int>(frame.data[i]);
  }
  return out.str();
}

std::string fault_text(uint16_t code)
{
  switch (code) {
    case 0x0000: return "no fault";
    case 0x0001: return "over voltage";
    case 0x0002: return "under voltage";
    case 0x0100: return "EEPROM read/write fault";
    case 0x0004: return "over current";
    case 0x0008: return "over load";
    case 0x0020: return "encoder deviation";
    case 0x0040: return "speed deviation";
    case 0x0080: return "reference voltage fault";
    case 0x0200: return "hall fault";
    case 0x0400: return "motor over temperature";
    case 0x0800: return "encoder fault";
    case 0x2000: return "target speed fault";
    default: break;
  }
  std::ostringstream out;
  out << "vendor fault 0x" << std::hex << std::uppercase << std::setw(4) << std::setfill('0') << code;
  return out.str();
}
}  // namespace

class DifferentialDriveKinematics
{
public:
  DifferentialDriveKinematics(
    double wheel_diameter, double wheel_track, double max_linear_velocity,
    double max_angular_velocity, double left_direction, double right_direction)
  : wheel_radius_(wheel_diameter * 0.5),
    wheel_track_(wheel_track),
    max_linear_velocity_(max_linear_velocity),
    max_angular_velocity_(max_angular_velocity),
    left_direction_(left_direction >= 0.0 ? 1.0 : -1.0),
    right_direction_(right_direction >= 0.0 ? 1.0 : -1.0)
  {
  }

  std::pair<double, double> twist_to_wheel_rpm(double linear_x, double angular_z) const
  {
    const double vx = clamp_value(linear_x, -max_linear_velocity_, max_linear_velocity_);
    const double wz = clamp_value(angular_z, -max_angular_velocity_, max_angular_velocity_);
    const double left_mps = vx - wz * wheel_track_ * 0.5;
    const double right_mps = vx + wz * wheel_track_ * 0.5;
    const double meters_per_rev = 2.0 * M_PI * wheel_radius_;
    return {
      left_direction_ * left_mps / meters_per_rev * 60.0,
      right_direction_ * right_mps / meters_per_rev * 60.0};
  }

  std::pair<double, double> wheel_rpm_to_twist(double left_rpm, double right_rpm) const
  {
    const double meters_per_rev = 2.0 * M_PI * wheel_radius_;
    const double left_mps = left_direction_ * left_rpm / 60.0 * meters_per_rev;
    const double right_mps = right_direction_ * right_rpm / 60.0 * meters_per_rev;
    return {(left_mps + right_mps) * 0.5, (right_mps - left_mps) / wheel_track_};
  }

private:
  double wheel_radius_;
  double wheel_track_;
  double max_linear_velocity_;
  double max_angular_velocity_;
  double left_direction_;
  double right_direction_;
};

class Zlac8015DCanopenClient
{
public:
  struct SdoResponse
  {
    uint16_t index = 0;
    uint8_t subindex = 0;
    uint8_t command = 0;
    uint32_t raw = 0;
    uint8_t size = 0;
  };

  Zlac8015DCanopenClient(
    const std::string & interface_name, uint8_t node_id, int sdo_timeout_ms,
    double target_velocity_unit_per_rpm, double actual_velocity_unit_per_rpm,
    rclcpp::Logger logger)
  : interface_name_(interface_name),
    node_id_(node_id),
    sdo_timeout_ms_(sdo_timeout_ms),
    target_velocity_unit_per_rpm_(target_velocity_unit_per_rpm),
    actual_velocity_unit_per_rpm_(actual_velocity_unit_per_rpm),
    logger_(logger)
  {
  }

  ~Zlac8015DCanopenClient()
  {
    close_socket();
  }

  bool open_socket()
  {
    socket_fd_ = socket(PF_CAN, SOCK_RAW | SOCK_NONBLOCK, CAN_RAW);
    if (socket_fd_ < 0) {
      RCLCPP_ERROR(logger_, "Failed to create SocketCAN socket: %s", std::strerror(errno));
      return false;
    }

    ifreq ifr {};
    std::strncpy(ifr.ifr_name, interface_name_.c_str(), IFNAMSIZ - 1);
    if (ioctl(socket_fd_, SIOCGIFINDEX, &ifr) < 0) {
      RCLCPP_ERROR(logger_, "CAN interface %s is not available: %s",
        interface_name_.c_str(), std::strerror(errno));
      close_socket();
      return false;
    }

    sockaddr_can addr {};
    addr.can_family = AF_CAN;
    addr.can_ifindex = ifr.ifr_ifindex;
    if (bind(socket_fd_, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0) {
      RCLCPP_ERROR(logger_, "Failed to bind %s: %s", interface_name_.c_str(), std::strerror(errno));
      close_socket();
      return false;
    }
    return true;
  }

  bool is_open() const { return socket_fd_ >= 0; }

  void close_socket()
  {
    if (socket_fd_ >= 0) {
      close(socket_fd_);
      socket_fd_ = -1;
    }
  }

  bool send_nmt_start()
  {
    can_frame frame {};
    frame.can_id = 0x000;
    frame.can_dlc = 2;
    frame.data[0] = 0x01;
    frame.data[1] = node_id_;
    return send_frame(frame);
  }

  bool write_u8(uint16_t index, uint8_t subindex, uint8_t value)
  {
    return send_sdo_write(index, subindex, 0x2F, value);
  }

  bool write_u16(uint16_t index, uint8_t subindex, uint16_t value)
  {
    return send_sdo_write(index, subindex, 0x2B, value);
  }

  bool write_i32(uint16_t index, uint8_t subindex, int32_t value)
  {
    return send_sdo_write(index, subindex, 0x23, static_cast<uint32_t>(value));
  }

  bool request_read(uint16_t index, uint8_t subindex)
  {
    can_frame frame {};
    frame.can_id = 0x600 + node_id_;
    frame.can_dlc = 8;
    frame.data[0] = 0x40;
    frame.data[1] = index & 0xFF;
    frame.data[2] = (index >> 8) & 0xFF;
    frame.data[3] = subindex;
    return send_frame(frame);
  }

  bool write_target_velocity(double left_rpm, double right_rpm)
  {
    const uint16_t left = static_cast<uint16_t>(rpm_to_target_units(left_rpm));
    const uint16_t right = static_cast<uint16_t>(rpm_to_target_units(right_rpm));
    const uint32_t packed = static_cast<uint32_t>(left) | (static_cast<uint32_t>(right) << 16);
    return write_i32(kTargetVelocity, 0x03, static_cast<int32_t>(packed));
  }

  bool initialize(bool fault_reset_on_start, int acceleration_rpm_per_sec, int deceleration_rpm_per_sec)
  {
    if (fault_reset_on_start && !write_and_wait_u16(kControlWord, 0x00, 0x0080)) {
      return false;
    }
    if (!send_nmt_start()) {
      return false;
    }
    rclcpp::sleep_for(50ms);

    return write_and_wait_u16(kVendorControlMode, 0x00, 1) &&
           write_and_wait_u8(kModesOfOperation, 0x00, 3) &&
           write_and_wait_i32(kProfileAcceleration, 0x01, acceleration_rpm_per_sec) &&
           write_and_wait_i32(kProfileAcceleration, 0x02, acceleration_rpm_per_sec) &&
           write_and_wait_i32(kProfileDeceleration, 0x01, deceleration_rpm_per_sec) &&
           write_and_wait_i32(kProfileDeceleration, 0x02, deceleration_rpm_per_sec) &&
           write_and_wait_u16(kControlWord, 0x00, 0x0006) &&
           write_and_wait_u16(kControlWord, 0x00, 0x0007) &&
           write_and_wait_u16(kControlWord, 0x00, 0x000F);
  }

  std::optional<SdoResponse> poll_once()
  {
    if (socket_fd_ < 0) {
      return std::nullopt;
    }

    can_frame frame {};
    const ssize_t n = read(socket_fd_, &frame, sizeof(frame));
    if (n < 0) {
      if (errno != EAGAIN && errno != EWOULDBLOCK) {
        RCLCPP_WARN_THROTTLE(logger_, *clock_, 2000, "CAN read failed: %s", std::strerror(errno));
      }
      return std::nullopt;
    }
    if (n != sizeof(frame)) {
      return std::nullopt;
    }

    const canid_t cob_id = frame.can_id & CAN_SFF_MASK;
    if (cob_id == static_cast<canid_t>(0x700 + node_id_)) {
      heartbeat_state_ = frame.can_dlc > 0 ? frame.data[0] : 0;
      heartbeat_seen_ = true;
      return std::nullopt;
    }
    if (cob_id != static_cast<canid_t>(0x580 + node_id_) || frame.can_dlc < 8) {
      RCLCPP_DEBUG(logger_, "Ignoring CAN frame %s", frame_to_string(frame).c_str());
      return std::nullopt;
    }
    if (frame.data[0] == 0x80) {
      const uint16_t index = frame.data[1] | (frame.data[2] << 8);
      const uint8_t subindex = frame.data[3];
      const uint32_t abort_code = frame.data[4] | (frame.data[5] << 8) |
        (frame.data[6] << 16) | (frame.data[7] << 24);
      RCLCPP_ERROR(logger_, "SDO abort 0x%04X:%02X code=0x%08X", index, subindex, abort_code);
      return SdoResponse{index, subindex, frame.data[0], abort_code, 4};
    }

    const uint16_t index = frame.data[1] | (frame.data[2] << 8);
    const uint8_t subindex = frame.data[3];
    const uint32_t raw = frame.data[4] | (frame.data[5] << 8) |
      (frame.data[6] << 16) | (frame.data[7] << 24);
    const uint8_t size = response_size(frame.data[0]);
    return SdoResponse{index, subindex, frame.data[0], raw, size};
  }

  void set_clock(rclcpp::Clock::SharedPtr clock) { clock_ = clock; }

  std::optional<std::pair<double, double>> decode_actual_rpm(const SdoResponse & response) const
  {
    if (response.index != kActualVelocity || response.subindex != 0x03) {
      return std::nullopt;
    }
    const int16_t left_raw = static_cast<int16_t>(response.raw & 0xFFFF);
    const int16_t right_raw = static_cast<int16_t>((response.raw >> 16) & 0xFFFF);
    return std::make_pair(
      static_cast<double>(left_raw) / actual_velocity_unit_per_rpm_,
      static_cast<double>(right_raw) / actual_velocity_unit_per_rpm_);
  }

  std::optional<uint32_t> decode_fault(const SdoResponse & response) const
  {
    if (response.index != kFaultCode) {
      return std::nullopt;
    }
    return response.raw;
  }

  bool heartbeat_seen() const { return heartbeat_seen_; }
  uint8_t heartbeat_state() const { return heartbeat_state_; }

private:
  bool send_frame(const can_frame & frame)
  {
    if (socket_fd_ < 0) {
      return false;
    }
    const ssize_t n = write(socket_fd_, &frame, sizeof(frame));
    if (n != sizeof(frame)) {
      RCLCPP_ERROR_THROTTLE(logger_, *clock_, 2000, "CAN write failed: %s", std::strerror(errno));
      return false;
    }
    return true;
  }

  bool send_sdo_write(uint16_t index, uint8_t subindex, uint8_t command, uint32_t value)
  {
    can_frame frame {};
    frame.can_id = 0x600 + node_id_;
    frame.can_dlc = 8;
    frame.data[0] = command;
    frame.data[1] = index & 0xFF;
    frame.data[2] = (index >> 8) & 0xFF;
    frame.data[3] = subindex;
    frame.data[4] = value & 0xFF;
    frame.data[5] = (value >> 8) & 0xFF;
    frame.data[6] = (value >> 16) & 0xFF;
    frame.data[7] = (value >> 24) & 0xFF;
    return send_frame(frame);
  }

  bool write_and_wait_u8(uint16_t index, uint8_t subindex, uint8_t value)
  {
    return write_u8(index, subindex, value) && wait_for_ack(index, subindex);
  }

  bool write_and_wait_u16(uint16_t index, uint8_t subindex, uint16_t value)
  {
    return write_u16(index, subindex, value) && wait_for_ack(index, subindex);
  }

  bool write_and_wait_i32(uint16_t index, uint8_t subindex, int32_t value)
  {
    return write_i32(index, subindex, value) && wait_for_ack(index, subindex);
  }

  bool wait_for_ack(uint16_t index, uint8_t subindex)
  {
    const auto start = std::chrono::steady_clock::now();
    while (std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now() - start).count() < sdo_timeout_ms_)
    {
      auto response = poll_once();
      if (response && response->index == index && response->subindex == subindex) {
        return response->command == 0x60;
      }
      rclcpp::sleep_for(2ms);
    }
    RCLCPP_ERROR(logger_, "Timeout waiting SDO ack 0x%04X:%02X", index, subindex);
    return false;
  }

  int32_t rpm_to_target_units(double rpm) const
  {
    const double scaled = std::round(rpm * target_velocity_unit_per_rpm_);
    return static_cast<int32_t>(clamp_value(
      scaled, static_cast<double>(std::numeric_limits<int16_t>::min()),
      static_cast<double>(std::numeric_limits<int16_t>::max())));
  }

  uint8_t response_size(uint8_t command) const
  {
    if (command == 0x4F) {
      return 1;
    }
    if (command == 0x4B) {
      return 2;
    }
    if (command == 0x43) {
      return 4;
    }
    if (command == 0x60) {
      return 0;
    }
    return 4;
  }

  std::string interface_name_;
  uint8_t node_id_;
  int sdo_timeout_ms_;
  double target_velocity_unit_per_rpm_;
  double actual_velocity_unit_per_rpm_;
  rclcpp::Logger logger_;
  rclcpp::Clock::SharedPtr clock_ = std::make_shared<rclcpp::Clock>(RCL_ROS_TIME);
  int socket_fd_ = -1;
  bool heartbeat_seen_ = false;
  uint8_t heartbeat_state_ = 0;
};

class OdometryIntegrator
{
public:
  OdometryIntegrator(const std::string & odom_frame, const std::string & base_frame)
  : odom_frame_(odom_frame), base_frame_(base_frame)
  {
  }

  nav_msgs::msg::Odometry update(const rclcpp::Time & stamp, double vx, double wz)
  {
    if (last_time_.nanoseconds() == 0) {
      last_time_ = stamp;
    }
    const double dt = std::max(0.0, (stamp - last_time_).seconds());
    last_time_ = stamp;

    x_ += vx * std::cos(yaw_) * dt;
    y_ += vx * std::sin(yaw_) * dt;
    yaw_ += wz * dt;

    tf2::Quaternion q;
    q.setRPY(0.0, 0.0, yaw_);

    nav_msgs::msg::Odometry odom;
    odom.header.stamp = stamp;
    odom.header.frame_id = odom_frame_;
    odom.child_frame_id = base_frame_;
    odom.pose.pose.position.x = x_;
    odom.pose.pose.position.y = y_;
    odom.pose.pose.position.z = 0.0;
    odom.pose.pose.orientation = tf2::toMsg(q);
    odom.twist.twist.linear.x = vx;
    odom.twist.twist.angular.z = wz;

    odom.pose.covariance[0] = 0.001;
    odom.pose.covariance[7] = 0.001;
    odom.pose.covariance[14] = 1e6;
    odom.pose.covariance[21] = 1e6;
    odom.pose.covariance[28] = 1e6;
    odom.pose.covariance[35] = 0.01;
    odom.twist.covariance[0] = 0.001;
    odom.twist.covariance[7] = 1e6;
    odom.twist.covariance[14] = 1e6;
    odom.twist.covariance[21] = 1e6;
    odom.twist.covariance[28] = 1e6;
    odom.twist.covariance[35] = 0.01;
    return odom;
  }

private:
  std::string odom_frame_;
  std::string base_frame_;
  rclcpp::Time last_time_;
  double x_ = 0.0;
  double y_ = 0.0;
  double yaw_ = 0.0;
};

class Zlac8015DCanopenController : public rclcpp::Node
{
public:
  Zlac8015DCanopenController()
  : Node("zlac8015d_canopen_controller")
  {
    declare_parameters();
    load_parameters();

    kinematics_ = std::make_unique<DifferentialDriveKinematics>(
      wheel_diameter_, wheel_track_, max_linear_velocity_, max_angular_velocity_,
      left_direction_, right_direction_);
    odom_integrator_ = std::make_unique<OdometryIntegrator>(odom_frame_, base_frame_);
    client_ = std::make_unique<Zlac8015DCanopenClient>(
      can_interface_, static_cast<uint8_t>(node_id_), sdo_timeout_ms_,
      target_velocity_unit_per_rpm_, actual_velocity_unit_per_rpm_, get_logger());
    client_->set_clock(get_clock());

    cmd_vel_sub_ = create_subscription<geometry_msgs::msg::Twist>(
      "cmd_vel", 10, std::bind(&Zlac8015DCanopenController::cmd_vel_callback, this, std::placeholders::_1));
    odom_pub_ = create_publisher<nav_msgs::msg::Odometry>("odom", 10);
    status_pub_ = create_publisher<std_msgs::msg::String>("zlac8015d/status", 10);
    fault_pub_ = create_publisher<std_msgs::msg::String>("zlac8015d/fault", 10);
    tf_broadcaster_ = std::make_unique<tf2_ros::TransformBroadcaster>(*this);

    if (use_pdo_) {
      RCLCPP_WARN(get_logger(), "use_pdo is reserved for a later version; this node uses SDO only.");
    }

    online_ = client_->open_socket();
    if (online_) {
      online_ = client_->initialize(fault_reset_on_start_, acceleration_rpm_per_sec_, deceleration_rpm_per_sec_);
    }
    if (!online_) {
      RCLCPP_ERROR(get_logger(),
        "ZLAC8015D backend is offline. Check %s and run scripts/setup_zlac_can.sh.",
        can_interface_.c_str());
    } else {
      RCLCPP_INFO(get_logger(), "ZLAC8015D CANopen backend started on %s node_id=%d",
        can_interface_.c_str(), node_id_);
    }

    last_cmd_time_ = now();
    create_timers();
  }

  ~Zlac8015DCanopenController() override
  {
    if (stop_on_exit_ && client_ && client_->is_open()) {
      client_->write_target_velocity(0.0, 0.0);
      rclcpp::sleep_for(50ms);
    }
  }

private:
  void declare_parameters()
  {
    declare_parameter<std::string>("can_interface", "can0");
    declare_parameter<int>("node_id", 1);
    declare_parameter<double>("wheel_diameter", 0.152);
    declare_parameter<double>("wheel_track", 0.25);
    declare_parameter<double>("max_linear_velocity", 0.6);
    declare_parameter<double>("max_angular_velocity", 1.2);
    declare_parameter<double>("left_direction", 1.0);
    declare_parameter<double>("right_direction", 1.0);
    declare_parameter<std::string>("odom_frame", "odom");
    declare_parameter<std::string>("base_frame", "base_footprint");
    declare_parameter<bool>("publish_tf", false);
    declare_parameter<bool>("fault_reset_on_start", true);
    declare_parameter<bool>("stop_on_exit", true);
    declare_parameter<bool>("use_pdo", false);
    declare_parameter<double>("control_rate_hz", 50.0);
    declare_parameter<double>("feedback_rate_hz", 20.0);
    declare_parameter<double>("fault_check_rate_hz", 2.0);
    declare_parameter<double>("can_poll_rate_hz", 200.0);
    declare_parameter<double>("cmd_timeout_sec", 0.5);
    declare_parameter<int>("sdo_timeout_ms", 200);
    declare_parameter<double>("target_velocity_unit_per_rpm", 1.0);
    declare_parameter<double>("actual_velocity_unit_per_rpm", 10.0);
    declare_parameter<int>("acceleration_rpm_per_sec", 300);
    declare_parameter<int>("deceleration_rpm_per_sec", 300);
  }

  void load_parameters()
  {
    get_parameter("can_interface", can_interface_);
    get_parameter("node_id", node_id_);
    get_parameter("wheel_diameter", wheel_diameter_);
    get_parameter("wheel_track", wheel_track_);
    get_parameter("max_linear_velocity", max_linear_velocity_);
    get_parameter("max_angular_velocity", max_angular_velocity_);
    get_parameter("left_direction", left_direction_);
    get_parameter("right_direction", right_direction_);
    get_parameter("odom_frame", odom_frame_);
    get_parameter("base_frame", base_frame_);
    get_parameter("publish_tf", publish_tf_);
    get_parameter("fault_reset_on_start", fault_reset_on_start_);
    get_parameter("stop_on_exit", stop_on_exit_);
    get_parameter("use_pdo", use_pdo_);
    get_parameter("control_rate_hz", control_rate_hz_);
    get_parameter("feedback_rate_hz", feedback_rate_hz_);
    get_parameter("fault_check_rate_hz", fault_check_rate_hz_);
    get_parameter("can_poll_rate_hz", can_poll_rate_hz_);
    get_parameter("cmd_timeout_sec", cmd_timeout_sec_);
    get_parameter("sdo_timeout_ms", sdo_timeout_ms_);
    get_parameter("target_velocity_unit_per_rpm", target_velocity_unit_per_rpm_);
    get_parameter("actual_velocity_unit_per_rpm", actual_velocity_unit_per_rpm_);
    get_parameter("acceleration_rpm_per_sec", acceleration_rpm_per_sec_);
    get_parameter("deceleration_rpm_per_sec", deceleration_rpm_per_sec_);
  }

  void create_timers()
  {
    can_poll_timer_ = create_wall_timer(period_from_hz(can_poll_rate_hz_),
      std::bind(&Zlac8015DCanopenController::poll_can, this));
    feedback_timer_ = create_wall_timer(period_from_hz(feedback_rate_hz_),
      std::bind(&Zlac8015DCanopenController::request_feedback, this));
    fault_timer_ = create_wall_timer(period_from_hz(fault_check_rate_hz_),
      std::bind(&Zlac8015DCanopenController::request_fault, this));
    watchdog_timer_ = create_wall_timer(period_from_hz(control_rate_hz_),
      std::bind(&Zlac8015DCanopenController::watchdog, this));
  }

  std::chrono::milliseconds period_from_hz(double hz) const
  {
    const double safe_hz = std::max(0.1, hz);
    return std::chrono::milliseconds(static_cast<int>(std::round(1000.0 / safe_hz)));
  }

  void cmd_vel_callback(const geometry_msgs::msg::Twist::SharedPtr msg)
  {
    last_cmd_time_ = now();
    timed_out_ = false;
    if (!online_) {
      return;
    }
    const auto [left_rpm, right_rpm] = kinematics_->twist_to_wheel_rpm(msg->linear.x, msg->angular.z);
    client_->write_target_velocity(left_rpm, right_rpm);
  }

  void poll_can()
  {
    if (!online_) {
      publish_status("offline");
      return;
    }

    for (int i = 0; i < 32; ++i) {
      auto response = client_->poll_once();
      if (!response) {
        break;
      }

      if (auto rpm = client_->decode_actual_rpm(*response)) {
        left_actual_rpm_ = rpm->first;
        right_actual_rpm_ = rpm->second;
        publish_odom();
      }

      if (auto fault = client_->decode_fault(*response)) {
        handle_fault(*fault, response->subindex);
      }
    }
    publish_status("online");
  }

  void request_feedback()
  {
    if (!online_) {
      return;
    }
    client_->request_read(kActualVelocity, 0x03);
  }

  void request_fault()
  {
    if (!online_) {
      return;
    }
    client_->request_read(kStatusWord, 0x00);
    client_->request_read(kFaultCode, 0x00);
    client_->request_read(kFaultCode, 0x01);
    client_->request_read(kFaultCode, 0x02);
  }

  void watchdog()
  {
    if (!online_) {
      return;
    }
    const double age = (now() - last_cmd_time_).seconds();
    if (age > cmd_timeout_sec_) {
      if (!timed_out_) {
        RCLCPP_WARN(get_logger(), "/cmd_vel timeout %.3fs; sending zero target velocity", age);
        timed_out_ = true;
      }
      client_->write_target_velocity(0.0, 0.0);
    }
  }

  void publish_odom()
  {
    const auto [vx, wz] = kinematics_->wheel_rpm_to_twist(left_actual_rpm_, right_actual_rpm_);
    auto odom = odom_integrator_->update(now(), vx, wz);
    odom_pub_->publish(odom);

    if (publish_tf_) {
      geometry_msgs::msg::TransformStamped tf;
      tf.header = odom.header;
      tf.child_frame_id = odom.child_frame_id;
      tf.transform.translation.x = odom.pose.pose.position.x;
      tf.transform.translation.y = odom.pose.pose.position.y;
      tf.transform.translation.z = 0.0;
      tf.transform.rotation = odom.pose.pose.orientation;
      tf_broadcaster_->sendTransform(tf);
    }
  }

  void handle_fault(uint32_t fault, uint8_t subindex)
  {
    if (fault == 0) {
      return;
    }
    client_->write_target_velocity(0.0, 0.0);
    const uint16_t right_fault = static_cast<uint16_t>(fault & 0xFFFF);
    const uint16_t left_fault = static_cast<uint16_t>((fault >> 16) & 0xFFFF);
    std::ostringstream msg;
    msg << "subindex=" << static_cast<int>(subindex) << " raw=0x" << std::hex << std::uppercase
        << std::setw(8) << std::setfill('0') << fault
        << " left=0x" << std::setw(4) << left_fault << "(" << fault_text(left_fault) << ")"
        << " right=0x" << std::setw(4) << right_fault << "(" << fault_text(right_fault) << ")";
    std_msgs::msg::String out;
    out.data = msg.str();
    fault_pub_->publish(out);
    RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 2000, "ZLAC8015D fault: %s", out.data.c_str());
  }

  void publish_status(const std::string & state)
  {
    std::ostringstream msg;
    msg << state << " heartbeat_seen=" << (client_ && client_->heartbeat_seen() ? "true" : "false")
        << " heartbeat_state=0x" << std::hex << std::uppercase << std::setw(2) << std::setfill('0')
        << static_cast<int>(client_ ? client_->heartbeat_state() : 0)
        << std::dec << " left_rpm=" << left_actual_rpm_ << " right_rpm=" << right_actual_rpm_
        << " timed_out=" << (timed_out_ ? "true" : "false");
    std_msgs::msg::String out;
    out.data = msg.str();
    status_pub_->publish(out);
  }

  std::string can_interface_;
  int node_id_ = 1;
  double wheel_diameter_ = 0.152;
  double wheel_track_ = 0.25;
  double max_linear_velocity_ = 0.6;
  double max_angular_velocity_ = 1.2;
  double left_direction_ = 1.0;
  double right_direction_ = 1.0;
  std::string odom_frame_ = "odom";
  std::string base_frame_ = "base_footprint";
  bool publish_tf_ = false;
  bool fault_reset_on_start_ = true;
  bool stop_on_exit_ = true;
  bool use_pdo_ = false;
  double control_rate_hz_ = 50.0;
  double feedback_rate_hz_ = 20.0;
  double fault_check_rate_hz_ = 2.0;
  double can_poll_rate_hz_ = 200.0;
  double cmd_timeout_sec_ = 0.5;
  int sdo_timeout_ms_ = 200;
  double target_velocity_unit_per_rpm_ = 1.0;
  double actual_velocity_unit_per_rpm_ = 10.0;
  int acceleration_rpm_per_sec_ = 300;
  int deceleration_rpm_per_sec_ = 300;

  bool online_ = false;
  bool timed_out_ = false;
  double left_actual_rpm_ = 0.0;
  double right_actual_rpm_ = 0.0;
  rclcpp::Time last_cmd_time_;

  std::unique_ptr<DifferentialDriveKinematics> kinematics_;
  std::unique_ptr<Zlac8015DCanopenClient> client_;
  std::unique_ptr<OdometryIntegrator> odom_integrator_;
  std::unique_ptr<tf2_ros::TransformBroadcaster> tf_broadcaster_;
  rclcpp::Subscription<geometry_msgs::msg::Twist>::SharedPtr cmd_vel_sub_;
  rclcpp::Publisher<nav_msgs::msg::Odometry>::SharedPtr odom_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr status_pub_;
  rclcpp::Publisher<std_msgs::msg::String>::SharedPtr fault_pub_;
  rclcpp::TimerBase::SharedPtr can_poll_timer_;
  rclcpp::TimerBase::SharedPtr feedback_timer_;
  rclcpp::TimerBase::SharedPtr fault_timer_;
  rclcpp::TimerBase::SharedPtr watchdog_timer_;
};

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv);
  auto node = std::make_shared<Zlac8015DCanopenController>();
  rclcpp::spin(node);
  rclcpp::shutdown();
  return 0;
}
