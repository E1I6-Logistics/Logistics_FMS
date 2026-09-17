# ROS 2 Launch 시스템을 구성하기 위해 필요한 기본 모듈과 액션, 치환(Substitution) 함수들을 가져옵니다.
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration, PythonExpression, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare

# Launch 파일을 실행할 때(ros2 launch ...) ROS 2가 가장 먼저 호출하여 실행할 작업 목록을 받아가는 메인 함수입니다.
def generate_launch_description():

    # Launch 실행 시 사용자가 외부에서 인자로 전달할 수 있는 'robot_id' 값을 가져와 변수에 저장합니다. (예: robot1, robot2)
    robot_id = LaunchConfiguration('robot_id')

    # robot1 -> /robot1
    # PythonExpression을 사용하여 위에서 받은 robot_id 문자열 앞에 슬래시('/')를 붙여 네임스페이스 형태(예: '/robot1')로 만듭니다. 
    # 이 변수는 하단 Zenoh 브릿지 실행 시 통신 토픽들의 접두사(Prefix)로 사용되어 메인 PC가 어떤 로봇인지 식별할 수 있게 해줍니다.
    bridge_namespace = PythonExpression([
        "'/' + '", robot_id, "'"
    ])

    # 브릿지 설정 파일인 bridge.json5의 절대 경로를 동적으로 생성합니다. 
    # 패키지(zenoh_pkg)가 설치된 경로를 찾고, 그 아래의 config 폴더 내에 있는 파일을 지정하여 하드코딩된 경로 없이 유연하게 파일을 찾게 해줍니다.
    config_file = PathJoinSubstitution([
        FindPackageShare('zenoh_pkg'),
        'config',
        'bridge.json5'
    ])

    # 최종적으로 실행될 액션(인자 선언, 노드 실행, 프로세스 실행 등)들의 리스트를 LaunchDescription 객체로 묶어 반환합니다.
    return LaunchDescription([

        # launch 명령어 실행 시 사용자가 'robot_id:=원하는이름' 형태로 값을 넘길 수 있도록 인자를 선언합니다. 값을 넘기지 않으면 기본값 'robot1'이 사용됩니다.
        DeclareLaunchArgument(
            'robot_id',
            default_value='robot1'
        ),

        # =====================================================
        # Robot Agent
        # namespace 없음
        #
        # 내부:
        #   /telemetry
        #   /goal
        #   /odom
        #   /cmd_vel
        #   ...
        # =====================================================
        # 실제 로봇의 동작(이동, 배터리 소모 등)을 시뮬레이션하는 파이썬 노드(robot_agent_test.py)를 실행합니다.
        # 여기서 주목할 점은 namespace를 따로 지정하지 않았다는 것입니다. 따라서 이 노드는 내부적으로 순수한 '/telemetry', '/goal' 토픽만 사용합니다.
        Node(
            package='zenoh_pkg',
            executable='robot_agent_test',
            name='robot_agent_test',
            output='screen',
            parameters=[
                {
                    # Launch 파일에서 받은 robot_id 값을 노드 내부의 파라미터로 전달하여, 노드가 자신이 몇 번 로봇인지 알게 합니다.
                    'robot_id': robot_id
                }
            ]
        ),

        # =====================================================
        # Zenoh Bridge
        #
        # Robot1:
        #   내부 /odom <-> 외부 /robot1/odom
        #
        # Robot2:
        #   내부 /odom <-> 외부 /robot2/odom
        #
        # 다른 robot namespace는 bridge.json5에서 차단
        # =====================================================
        # ROS 2의 DDS 통신을 Zenoh 프로토콜로 변환하여 외부 네트워크(Main PC)로 보내주는 브릿지 프로세스를 실행합니다.
        ExecuteProcess(
            cmd=[
                'zenoh-bridge-ros2dds',
                '-c',
                config_file,          # 위에서 찾은 bridge.json5 설정 파일을 적용하여 불필요한 토픽 유입을 막습니다.
                '-e',
                'tcp/10.10.141.15:7447', # Main PC(또는 Zenoh 라우터)의 IP와 포트 번호로 연결(client 모드)을 시도합니다.
                '-n',
                bridge_namespace,     # 에이전트 노드가 발행하는 순수 토픽('/telemetry')에 이 네임스페이스('/robot1')를 붙여서 외부로 보냅니다. (결과: '/robot1/telemetry')
                'client'
            ],
            output='screen'
        ),
    ])