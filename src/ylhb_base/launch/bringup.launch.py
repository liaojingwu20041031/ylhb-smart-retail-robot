import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, Command
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue

def generate_launch_description():
    pkg_dir = get_package_share_directory('ylhb_base')
    ekf_config_path = os.path.join(pkg_dir, 'config', 'ekf.yaml')
    rplidar_pkg_dir = get_package_share_directory('rplidar_ros')
    
    # 引入机器人模型的 urdf.xacro 文件定位
    urdf_file = os.path.join(pkg_dir, 'urdf', 'ylhb.urdf.xacro')

    # 声明变量作为启动参数（Launch Arguments），方便在命令行动态修改串口号
    base_port_arg = DeclareLaunchArgument(
        'base_port', default_value='/dev/ttyS1',
        description='Serial port for the base controller'
    )
    imu_port_arg = DeclareLaunchArgument(
        'imu_port', default_value='/dev/robot_imu',
        description='Serial port for the IMU sensor'
    )
    lidar_port_arg = DeclareLaunchArgument(
        'lidar_port', default_value='/dev/robot_lidar',
        description='Serial port for the LiDAR'
    )

    # 获取动态的参数值
    base_port = LaunchConfiguration('base_port')
    imu_port = LaunchConfiguration('imu_port')
    lidar_port = LaunchConfiguration('lidar_port')

    # 底盘控制节点，关闭其自身发布的 TF，让 EKF 接管
    base_node = Node(
        package='ylhb_base',
        executable='base_controller',
        name='base_controller',
        output='screen',
        parameters=[
            {'serial_port': base_port},
            {'publish_tf': False} # 重要：防止 TF 冲突
        ]
    )

    # IMU 驱动节点, 接收动态传入的串口参数
    imu_node = Node(
        package='ylhb_base',
        executable='imu_driver',
        name='imu_driver',
        output='screen',
        parameters=[
            {'serial_port': imu_port}
        ]
    )

    # 包含 rplidar 雷达启动文件，并把动态的端口传给它
    lidar_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(rplidar_pkg_dir, 'launch', 'rplidar_a2m8_launch.py')
        ),
        launch_arguments={
            'serial_port': lidar_port,
            'frame_id': 'laser_link'
        }.items()
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
        base_port_arg,
        imu_port_arg,
        lidar_port_arg,
        robot_state_publisher_node,
        base_node,
        imu_node,
        lidar_launch,
        ekf_node
    ])
