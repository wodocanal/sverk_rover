from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'rover_teleop'

setup(
    name=package_name,
    version='0.4.2',
    packages=find_packages(exclude=['test']),
    data_files=[
        (
            'share/ament_index/resource_index/packages',
            ['resource/' + package_name],
        ),
        ('share/' + package_name, ['package.xml']),
        (
            os.path.join('share', package_name, 'config'),
            glob('config/*.yaml'),
        ),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Rover Team',
    maintainer_email='maintainer@example.com',
    description='Safe terminal WASD teleoperation for the mecanum rover.',
    license='Apache-2.0',
    extras_require={'test': ['pytest']},
    entry_points={
        'console_scripts': [
            'mecanum_keyboard = rover_teleop.mecanum_keyboard:main',
            'mecanum_keyboard_mux = rover_teleop.mecanum_keyboard:main_mux',
        ],
    },
)
