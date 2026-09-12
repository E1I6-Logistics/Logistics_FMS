from setuptools import setup
from glob import glob
import os

package_name = 'zenoh_pkg'

setup(
    name=package_name,
    version='0.0.1',
    packages=[package_name],
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name]
        ),
        (
            'share/' + package_name,
            ['package.xml']
        ),
        (
            os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='turtlebot',
    maintainer_email='turtlebot@example.com',
    description='Zenoh communication package',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'robot_agent = zenoh_pkg.robot_agent:main',
        ],
    },
)
