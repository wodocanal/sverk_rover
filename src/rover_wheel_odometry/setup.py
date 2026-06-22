from setuptools import find_packages, setup
package_name = 'rover_wheel_odometry'
setup(
    name=package_name,
    version='0.2.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Rover Team', maintainer_email='maintainer@example.com',
    description='Four-wheel mecanum odometry from accumulated encoder counts.',
    license='Apache-2.0',
    entry_points={'console_scripts': [
        'wheel_odometry_node = rover_wheel_odometry.wheel_odometry_node:main',
    ]},
)
