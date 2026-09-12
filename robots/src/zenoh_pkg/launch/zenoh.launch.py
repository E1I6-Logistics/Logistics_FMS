from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    namespace = LaunchConfiguration('namespace')

    return LaunchDescription([

        # 로봇 이름
        DeclareLaunchArgument(
            'namespace',
            default_value='noname_robot'
        ),

        # Robot Agent
        Node(
            package='zenoh_pkg',
            executable='robot_agent',
            namespace=namespace,
            output='screen'
        ),

        # Zenoh ROS2DDS Bridge
        ExecuteProcess(
            cmd=[
                'zenoh-bridge-ros2dds',
                '-e',
                'tcp/10.10.141.15:7447',
                'client'
            ],
            output='screen'
        ),
    ])
