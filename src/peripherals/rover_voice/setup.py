from glob import glob
import os

from setuptools import find_packages, setup


package_name = 'rover_voice'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name, ['README.md']),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'udev'), glob('udev/*.rules')),
    ],
    install_requires=['setuptools', 'pyserial'],
    zip_safe=True,
    maintainer='Rover Team',
    maintainer_email='maintainer@example.com',
    description='Yahboom ASR/TTS voice interaction module driver for ROS 2.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'voice_module_node = rover_voice.voice_module_node:main',
        ],
    },
)
