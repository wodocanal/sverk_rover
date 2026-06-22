from glob import glob
from setuptools import find_packages, setup
import os

package_name = 'rover_bringup'
setup(
    name=package_name,
    version='0.4.3',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ],
    install_requires=['setuptools', 'PyYAML'],
    zip_safe=True,
    maintainer='Rover Team', maintainer_email='maintainer@example.com',
    description='Top-level rover hardware and localization bringup.',
    license='Apache-2.0',
)
