import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration, Command
from launch.substitutions import PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


DEFAULT_LIDAR_PORT = (
    '/dev/serial/by-id/'
    'usb-Silicon_Labs_CP2102_USB_to_UART_Bridge_Controller_0001-if00-port0'
)


def serial_preflight(context, *args, **kwargs):
    lidar_port = LaunchConfiguration('lidar_port').perform(context)
    imu_port = LaunchConfiguration('imu_port').perform(context)
    enable_imu = LaunchConfiguration('enable_imu').perform(context).lower() in ('1', 'true', 'yes', 'on')

    actions = []
    if not os.path.exists(lidar_port):
        actions.append(LogInfo(msg=(
            f'WARN: LiDAR serial port {lidar_port} does not exist. '
            'Check /dev/serial/by-id or pass lidar_port:=/dev/ttyUSBx.'
        )))

    if enable_imu and not os.path.exists(imu_port):
        actions.append(LogInfo(msg=(
            f'WARN: IMU serial port {imu_port} does not exist. '
            'If lsusb shows 1a86:7523 but no ttyUSB device, the Jetson kernel '
            'has not bound a CH340/ch341 tty driver.'
        )))

    return actions


def generate_launch_description():
    pkg_dir = get_package_share_directory('ylhb_base')
    ekf_config_path = os.path.join(pkg_dir, 'config', 'ekf.yaml')
    base_kinematics_path = os.path.join(pkg_dir, 'config', 'base_kinematics.yaml')
    zlac_config_path = os.path.join(pkg_dir, 'config', 'zlac8015d.yaml')

    # 引入机器人模型的 urdf.xacro 文件定位
    urdf_file = os.path.join(pkg_dir, 'urdf', 'ylhb.urdf.xacro')

    # 声明变量作为启动参数（Launch Arguments），方便在命令行动态修改串口号
    base_port_arg = DeclareLaunchArgument(
        'base_port', default_value='/dev/ttyS1',
        description='Serial port for the STM32 base controller fallback'
    )
    base_backend_arg = DeclareLaunchArgument(
        'base_backend', default_value='zlac',
        description='Chassis backend: zlac or stm32'
    )
    enable_imu_arg = DeclareLaunchArgument(
        'enable_imu', default_value='false',
        description='Enable IMU driver node'
    )
    imu_port_arg = DeclareLaunchArgument(
        'imu_port', default_value='/dev/robot_imu',
        description='Serial port for the IMU sensor'
    )
    lidar_port_arg = DeclareLaunchArgument(
        'lidar_port', default_value=DEFAULT_LIDAR_PORT,
        description='Serial port for the LiDAR'
    )
    lidar_baudrate_arg = DeclareLaunchArgument(
        'lidar_baudrate', default_value='115200',
        description='Serial baudrate for RPLidar A2M8'
    )
    lidar_frame_id_arg = DeclareLaunchArgument(
        'lidar_frame_id', default_value='laser_link',
        description='Frame id for RPLidar laser scans'
    )

    # 获取动态的参数值
    base_port = LaunchConfiguration('base_port')
    base_backend = LaunchConfiguration('base_backend')
    enable_imu = LaunchConfiguration('enable_imu')
    imu_port = LaunchConfiguration('imu_port')
    lidar_port = LaunchConfiguration('lidar_port')
    lidar_baudrate = LaunchConfiguration('lidar_baudrate')
    lidar_frame_id = LaunchConfiguration('lidar_frame_id')

    use_zlac = IfCondition(PythonExpression(["'", base_backend, "' == 'zlac'"]))
    use_stm32 = IfCondition(PythonExpression(["'", base_backend, "' == 'stm32'"]))

    # 默认 ZLAC8015D SocketCAN 底盘后端，关闭自身 TF，让 EKF 接管
    zlac_base_node = Node(
        package='ylhb_base',
        executable='zlac8015d_canopen_controller',
        name='zlac8015d_canopen_controller',
        output='screen',
        condition=use_zlac,
        parameters=[
            base_kinematics_path,
            zlac_config_path,
            {'publish_tf': False}
        ]
    )

    # STM32 串口底盘控制节点作为回退方案
    stm32_base_node = Node(
        package='ylhb_base',
        executable='base_controller',
        name='base_controller',
        output='screen',
        condition=use_stm32,
        parameters=[
            {'serial_port': base_port},
            {'publish_tf': False}  # 重要：防止 TF 冲突
        ]
    )

    # IMU 驱动节点, 接收动态传入的串口参数
    imu_node = Node(
        package='ylhb_base',
        executable='imu_driver',
        name='imu_driver',
        output='screen',
        condition=IfCondition(enable_imu),
        parameters=[
            {'serial_port': imu_port}
        ]
    )

    # 本仓库 rplidar_ros 参数名已确认是 serial_port/serial_baudrate/frame_id；
    # 若未来版本不兼容，可退回 IncludeLaunchDescription 的 A2M8 launch 方式。
    lidar_node = Node(
        package='rplidar_ros',
        executable='rplidar_node',
        name='rplidar_node',
        output='screen',
        parameters=[{
            'channel_type': 'serial',
            'serial_port': lidar_port,
            'serial_baudrate': ParameterValue(lidar_baudrate, value_type=int),
            'frame_id': lidar_frame_id,
            'inverted': False,
            'angle_compensate': True
        }]
    )

    # 机器人状态发布节点 (统一处理和发布机器人的全套物理 TF 关系)
    robot_state_publisher_node = Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{
            'robot_description': ParameterValue(Command(['xacro ', urdf_file]), value_type=str)
        }]
    )

    # Robot Localization EKF 节点
    ekf_node = Node(
        package='robot_localization',
        executable='ekf_node',
        name='ekf_filter_node',
        output='screen',
        parameters=[ekf_config_path]
    )

    return LaunchDescription([
        base_backend_arg,
        base_port_arg,
        enable_imu_arg,
        imu_port_arg,
        lidar_port_arg,
        lidar_baudrate_arg,
        lidar_frame_id_arg,
        OpaqueFunction(function=serial_preflight),
        robot_state_publisher_node,
        zlac_base_node,
        stm32_base_node,
        imu_node,
        lidar_node,
        ekf_node
    ])
