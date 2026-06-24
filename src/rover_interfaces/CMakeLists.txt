cmake_minimum_required(VERSION 3.8)
project(rover_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/LedStripState.msg"
  "msg/OctolinerReading.msg"
  "msg/WheelCommand.msg"
  "msg/WheelEncoders.msg"
  "srv/GetFrame.srv"
  "srv/SetLedStripState.srv"
  "srv/SetSensitivity.srv"
  DEPENDENCIES std_msgs sensor_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
