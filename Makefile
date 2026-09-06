DOCKER_COMPOSE ?= docker compose
ROS_SERVICE ?= ros
GUI_SERVICE ?= ros-gui
COLCON_FLAGS ?= --symlink-install --event-handlers console_direct+
SIM_WORLD ?= empty
SIM_MODE ?= idle
SIM_UI ?= web
SIM_GUI_PORT ?= 5901
SIM_GUI_RESOLUTION ?= 1600x1000
SIM_MAP ?= src/motion/rover_navigation/maps/current/map.yaml
SIM_FIELD_OUTPUT ?= src/simulation/rover_gazebo/worlds/field.sdf

.PHONY: help docker-build ros-build ros-test ros-smoke ros-check ros-shell \
	sim-world sim-run sim-gui-setup sim-gui sim-test sim-test-modes docker-down

help:
	@printf '%s\n' \
	  'make docker-build  Build the ROS 2 Jazzy development image' \
	  'make ros-build     Build all rover packages with colcon' \
	  'make ros-test      Run colcon tests and print all failures' \
	  'make ros-smoke     Check package launches and safe runtime nodes' \
	  'make ros-check     Run image build, workspace build, tests and smoke checks' \
	  'make ros-shell     Open an interactive ROS shell with UI ports exposed' \
	  'make sim-world     Regenerate field.sdf from SIM_MAP' \
	  'make sim-run       Run Gazebo headless (SIM_WORLD, SIM_MODE and SIM_UI)' \
	  'make sim-gui-setup Build the container image with Gazebo GUI support' \
	  'make sim-gui       Open Gazebo in a native macOS Screen Sharing window' \
	  'make sim-test      Verify simulated drive, odometry, lidar, IMU and camera' \
	  'make sim-test-modes Verify SLAM, a Nav2 goal, vision and the web API' \
	  'make docker-down   Stop Compose containers without deleting build volumes'

docker-build:
	$(DOCKER_COMPOSE) build $(ROS_SERVICE)

ros-build:
	$(DOCKER_COMPOSE) run --rm $(ROS_SERVICE) \
		colcon build $(COLCON_FLAGS)

ros-test: ros-build
	$(DOCKER_COMPOSE) run --rm $(ROS_SERVICE) bash -lc \
		'colcon test --python-testing pytest --return-code-on-test-failure \
		--event-handlers console_direct+ && colcon test-result --verbose'

ros-smoke: ros-build
	$(DOCKER_COMPOSE) run --rm $(ROS_SERVICE) \
		python3 docker/ros_smoke_test.py

ros-check: docker-build ros-test ros-smoke

ros-shell: docker-build
	$(DOCKER_COMPOSE) run --rm --service-ports $(ROS_SERVICE) bash

sim-run: ros-build
	$(DOCKER_COMPOSE) run --rm --service-ports $(ROS_SERVICE) \
		ros2 launch rover_bringup simulation.launch.py \
		world:=$(SIM_WORLD) mode:=$(SIM_MODE) ui_profile:=$(SIM_UI) \
		gui:=false headless_rendering:=true

sim-gui-setup:
	@if ! docker image inspect sverk-rover-ros:jazzy >/dev/null 2>&1; then \
		$(DOCKER_COMPOSE) build $(ROS_SERVICE); \
	fi
	$(DOCKER_COMPOSE) build $(GUI_SERVICE)
	@printf '%s\n' 'Gazebo GUI image is ready; run make sim-gui.'

sim-gui: sim-gui-setup ros-build
	SIM_WORLD=$(SIM_WORLD) SIM_MODE=$(SIM_MODE) SIM_UI=$(SIM_UI) \
		SIM_GUI_PORT=$(SIM_GUI_PORT) SIM_GUI_RESOLUTION=$(SIM_GUI_RESOLUTION) \
		GUI_SERVICE=$(GUI_SERVICE) ./docker/run_gazebo_gui_macos.sh

sim-world: ros-build
	$(DOCKER_COMPOSE) run --rm $(ROS_SERVICE) \
		ros2 run rover_gazebo map_to_world \
		--map /workspace/$(SIM_MAP) --output /workspace/$(SIM_FIELD_OUTPUT)

sim-test: ros-build
	$(DOCKER_COMPOSE) run --rm $(ROS_SERVICE) \
		python3 docker/gazebo_smoke_test.py

sim-test-modes: ros-build
	$(DOCKER_COMPOSE) run --rm $(ROS_SERVICE) \
		python3 docker/gazebo_modes_smoke_test.py mapping
	$(DOCKER_COMPOSE) run --rm $(ROS_SERVICE) \
		python3 docker/gazebo_modes_smoke_test.py navigation

docker-down:
	$(DOCKER_COMPOSE) down
