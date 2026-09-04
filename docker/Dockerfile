FROM ros:jazzy-ros-base-noble

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    ROS_DISTRO=jazzy \
    ROVER_WS=/workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash-completion \
        build-essential \
        ca-certificates \
        curl \
        git \
        iproute2 \
        locales \
        libegl1 \
        libgl1-mesa-dri \
        mesa-utils \
        procps \
        python3-colcon-common-extensions \
        python3-pip \
        python3-pytest \
        python3-rosdep \
    && rm -rf /var/lib/apt/lists/*

# Install all package.xml dependencies into the reusable development image.
# The live source tree is mounted at /workspace by Docker Compose.
COPY src /tmp/rover-src
COPY docker/install_dependencies.sh /tmp/install_dependencies.sh
RUN chmod +x /tmp/install_dependencies.sh \
    && /tmp/install_dependencies.sh /tmp/rover-src \
    && rm -rf /tmp/rover-src /var/lib/apt/lists/*

COPY docker/entrypoint.sh /ros_entrypoint_rover.sh
RUN chmod +x /ros_entrypoint_rover.sh

WORKDIR /workspace
ENTRYPOINT ["/ros_entrypoint_rover.sh"]
CMD ["bash"]
