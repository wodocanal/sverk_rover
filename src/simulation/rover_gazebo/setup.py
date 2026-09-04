from glob import glob
import os

from setuptools import find_packages, setup


package_name = 'rover_gazebo'


setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'urdf'), glob('urdf/*.xacro')),
        (os.path.join('share', package_name, 'worlds'), glob('worlds/*.sdf')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Rover Team',
    maintainer_email='maintainer@example.com',
    description='Gazebo Harmonic simulation of the Sverk mecanum rover.',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'camera_adapter = rover_gazebo.camera_adapter:main',
            'encoder_adapter = rover_gazebo.encoder_adapter:main',
            'initial_pose = rover_gazebo.initial_pose:main',
            'map_to_world = rover_gazebo.map_to_world:main',
            'mock_io = rover_gazebo.mock_io:main',
            'twist_adapter = rover_gazebo.twist_adapter:main',
        ],
    },
)
