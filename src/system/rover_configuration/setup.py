from setuptools import find_packages, setup

setup(
    name='rover_configuration',
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/rover_configuration']),
        ('share/rover_configuration', ['package.xml']),
    ],
    install_requires=['setuptools', 'PyYAML'],
    tests_require=['pytest'],
    zip_safe=True,
    maintainer='Rover Team',
    maintainer_email='maintainer@example.com',
    description='Shared YAML loading utilities, without robot-specific settings.',
    license='Apache-2.0',
)
