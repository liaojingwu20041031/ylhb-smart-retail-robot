#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#include <cmath>
#include <tf2/LinearMath/Quaternion.h>

class IMUDriver : public rclcpp::Node
{
public:
    IMUDriver() : Node("imu_driver")
    {
        this->declare_parameter<std::string>("serial_port", "/dev/ttyUSB0");
        this->declare_parameter<std::string>("frame_id", "imu_link");
        this->get_parameter("serial_port", serial_port_);
        this->get_parameter("frame_id", frame_id_);

        imu_pub_ = this->create_publisher<sensor_msgs::msg::Imu>("imu/data", 10);

        // Try open at 115200 first
        if (!initSerial(B115200)) {
            RCLCPP_ERROR(this->get_logger(), "Failed to open serial port %s", serial_port_.c_str());
            return;
        }

        // Configure IMU (Unlock -> set baud -> set rate -> save)
        configureIMU();

        timer_ = this->create_wall_timer(
            std::chrono::milliseconds(5), std::bind(&IMUDriver::readLoop, this));
            
        RCLCPP_INFO(this->get_logger(), "IMU Driver Started on %s", serial_port_.c_str());
    }

    ~IMUDriver()
    {
        if (serial_fd_ > 0) close(serial_fd_);
    }

private:
    std::string serial_port_;
    std::string frame_id_;
    int serial_fd_ = -1;

    rclcpp::Publisher<sensor_msgs::msg::Imu>::SharedPtr imu_pub_;
    rclcpp::TimerBase::SharedPtr timer_;

    sensor_msgs::msg::Imu imu_msg_;
    bool acc_ready = false, gyro_ready = false, angle_ready = false;

    bool initSerial(speed_t baudrate)
    {
        if (serial_fd_ > 0) close(serial_fd_);
        serial_fd_ = open(serial_port_.c_str(), O_RDWR | O_NOCTTY | O_NDELAY);
        if (serial_fd_ == -1) return false;

        struct termios options;
        tcgetattr(serial_fd_, &options);
        cfsetispeed(&options, baudrate);
        cfsetospeed(&options, baudrate);

        options.c_cflag |= (CLOCAL | CREAD);
        options.c_cflag &= ~PARENB;
        options.c_cflag &= ~CSTOPB;
        options.c_cflag &= ~CSIZE;
        options.c_cflag |= CS8;
        options.c_lflag &= ~(ICANON | ECHO | ECHOE | ISIG);
        options.c_oflag &= ~OPOST;
        options.c_cc[VMIN] = 0;
        options.c_cc[VTIME] = 0;

        tcsetattr(serial_fd_, TCSANOW, &options);
        return true;
    }

    void sendCmd(const std::vector<uint8_t>& cmd) {
        if (serial_fd_ > 0) {
            write(serial_fd_, cmd.data(), cmd.size());
            usleep(200000); // 200ms delay
        }
    }

    void configureIMU()
    {
        // Unlock
        sendCmd({0xFF, 0xAA, 0x69, 0x88, 0xB5});
        // Change baudrate to 115200
        sendCmd({0xFF, 0xAA, 0x04, 0x06, 0x00});
        // Assuming 100Hz is 0x0B based on WIT protocol
        sendCmd({0xFF, 0xAA, 0x03, 0x0B, 0x00});
        // Save
        sendCmd({0xFF, 0xAA, 0x00, 0x00, 0x00});

        // Re-open with 115200 just in case
        initSerial(B115200);
        
        // Re-unlock and save after baud change just in case the module needs it per baud step
        sendCmd({0xFF, 0xAA, 0x69, 0x88, 0xB5});
        sendCmd({0xFF, 0xAA, 0x00, 0x00, 0x00});
    }

    void readLoop()
    {
        if (serial_fd_ < 0) return;

        uint8_t rx_buf[1024];
        int n = read(serial_fd_, rx_buf, sizeof(rx_buf));

        if (n > 0) {
            for (int i = 0; i < n - 10; i++) {
                if (rx_buf[i] == 0x55) {
                    uint8_t type = rx_buf[i+1];
                    uint8_t sum = 0;
                    for (int j = 0; j < 10; j++) sum += rx_buf[i+j];
                    
                    if (sum == rx_buf[i+10]) {
                        parseData(type, &rx_buf[i+2]);
                        i += 10; // Skip parsed packet
                    }
                }
            }
        }
    }

    void parseData(uint8_t type, uint8_t* data)
    {
        if (type == 0x51) { // Acc
            int16_t ax = (data[1] << 8) | data[0];
            int16_t ay = (data[3] << 8) | data[2];
            int16_t az = (data[5] << 8) | data[4];
            
            double a_x_raw = (ax / 32768.0) * 16.0 * 9.8;
            double a_y_raw = (ay / 32768.0) * 16.0 * 9.8;
            double a_z_raw = (az / 32768.0) * 16.0 * 9.8;
            
            // 传感器 Y为前进，X为右。映射到 ROS 的 X(前) Y(左) Z(上)
            imu_msg_.linear_acceleration.x = a_y_raw;   // 前
            imu_msg_.linear_acceleration.y = -a_x_raw;  // 左
            imu_msg_.linear_acceleration.z = a_z_raw;   // 上
            acc_ready = true;
        }
        else if (type == 0x52) { // Gyro
            int16_t wx = (data[1] << 8) | data[0];
            int16_t wy = (data[3] << 8) | data[2];
            int16_t wz = (data[5] << 8) | data[4];
            
            double w_x_raw = (wx / 32768.0) * 2000.0 * M_PI / 180.0;
            double w_y_raw = (wy / 32768.0) * 2000.0 * M_PI / 180.0;
            double w_z_raw = (wz / 32768.0) * 2000.0 * M_PI / 180.0;
            
            // 角速度映射规则与加速度一致
            imu_msg_.angular_velocity.x = w_y_raw;
            imu_msg_.angular_velocity.y = -w_x_raw;
            imu_msg_.angular_velocity.z = w_z_raw;
            gyro_ready = true;
        }
        else if (type == 0x53) { // Angle
            int16_t roll = (data[1] << 8) | data[0];
            int16_t pitch = (data[3] << 8) | data[2];
            int16_t yaw = (data[5] << 8) | data[4];
            
            double r_raw = (roll / 32768.0) * M_PI;
            double p_raw = (pitch / 32768.0) * M_PI;
            double y_raw = (yaw / 32768.0) * M_PI;

            // ROS中的Roll对应传感器绕前进轴(Y轴)旋转的角度，即Pitch
            // ROS中的Pitch对应传感器绕左侧轴(-X轴)旋转的角度，即 -Roll
            // ROS中的Yaw对应传感器绕垂直轴(Z轴)旋转的角度，即Yaw
            double ros_roll = p_raw;
            double ros_pitch = -r_raw;
            double ros_yaw = y_raw;

            tf2::Quaternion q;
            q.setRPY(ros_roll, ros_pitch, ros_yaw);
            
            imu_msg_.orientation.x = q.x();
            imu_msg_.orientation.y = q.y();
            imu_msg_.orientation.z = q.z();
            imu_msg_.orientation.w = q.w();
            angle_ready = true;
        }

        // Publish when all parts received (usually sent in burst)
        if (acc_ready && gyro_ready && angle_ready) {
            
            // 为IMU数据添加协方差，滤波算法必须需要该参数评估数据置信度
            imu_msg_.orientation_covariance = {0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01};
            imu_msg_.angular_velocity_covariance = {0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01};
            imu_msg_.linear_acceleration_covariance = {0.01, 0, 0, 0, 0.01, 0, 0, 0, 0.01};

            imu_msg_.header.stamp = this->now();
            imu_msg_.header.frame_id = frame_id_;
            imu_pub_->publish(imu_msg_);
            
            acc_ready = false;
            gyro_ready = false;
            angle_ready = false;
        }
    }
};

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);
    auto node = std::make_shared<IMUDriver>();
    rclcpp::spin(node);
    rclcpp::shutdown();
    return 0;
}
