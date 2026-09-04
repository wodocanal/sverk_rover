from __future__ import annotations

import argparse
from pathlib import Path
from xml.sax.saxutils import escape

from ament_index_python.packages import get_package_share_directory
import yaml


def _next_token(data: bytes, offset: int) -> tuple[bytes, int]:
    while offset < len(data):
        if data[offset] == ord('#'):
            newline = data.find(b'\n', offset)
            offset = len(data) if newline < 0 else newline + 1
        elif chr(data[offset]).isspace():
            offset += 1
        else:
            break
    end = offset
    while end < len(data) and not chr(data[end]).isspace() and data[end] != ord('#'):
        end += 1
    if end == offset:
        raise ValueError('Unexpected end of PGM header')
    return data[offset:end], end


def read_pgm(path: Path) -> tuple[int, int, list[int]]:
    data = path.read_bytes()
    magic, offset = _next_token(data, 0)
    width_raw, offset = _next_token(data, offset)
    height_raw, offset = _next_token(data, offset)
    max_value_raw, offset = _next_token(data, offset)
    width = int(width_raw)
    height = int(height_raw)
    max_value = int(max_value_raw)
    if width <= 0 or height <= 0 or not 0 < max_value <= 255:
        raise ValueError(f'Unsupported PGM dimensions or depth in {path}')

    if magic == b'P5':
        if offset >= len(data) or not chr(data[offset]).isspace():
            raise ValueError(f'Missing PGM raster separator in {path}')
        offset += 1
        if data[offset - 1:offset] == b'\r' and data[offset:offset + 1] == b'\n':
            offset += 1
        pixels = list(data[offset:offset + width * height])
    elif magic == b'P2':
        pixels = []
        for _ in range(width * height):
            token, offset = _next_token(data, offset)
            pixels.append(int(token))
    else:
        raise ValueError(f'Only P2/P5 PGM maps are supported, got {magic!r}')

    if len(pixels) != width * height:
        raise ValueError(f'PGM raster is truncated: expected {width * height} pixels')
    if max_value != 255:
        pixels = [round(value * 255 / max_value) for value in pixels]
    return width, height, pixels


def occupied_rectangles(
    width: int,
    height: int,
    pixels: list[int],
    *,
    occupied_threshold: float,
    negate: bool,
    min_cells: int,
) -> list[tuple[int, int, int, int]]:
    def occupied(pixel: int) -> bool:
        probability = pixel / 255.0 if negate else (255 - pixel) / 255.0
        return probability >= occupied_threshold

    rectangles: list[tuple[int, int, int, int]] = []
    active: dict[tuple[int, int], int] = {}
    for row in range(height):
        runs = []
        column = 0
        while column < width:
            if not occupied(pixels[row * width + column]):
                column += 1
                continue
            start = column
            while column + 1 < width and occupied(
                pixels[row * width + column + 1]
            ):
                column += 1
            runs.append((start, column))
            column += 1

        current = set(runs)
        for run, start_row in active.items():
            if run not in current:
                rectangles.append((run[0], run[1], start_row, row - 1))
        active = {
            run: active.get(run, row)
            for run in runs
        }

    for run, start_row in active.items():
        rectangles.append((run[0], run[1], start_row, height - 1))
    return [
        rectangle for rectangle in rectangles
        if ((rectangle[1] - rectangle[0] + 1)
            * (rectangle[3] - rectangle[2] + 1)) >= min_cells
    ]


def render_world(
    map_yaml: Path,
    *,
    wall_height: float,
    min_cells: int,
    add_boundary: bool,
) -> tuple[str, int]:
    config = yaml.safe_load(map_yaml.read_text(encoding='utf-8')) or {}
    image_path = Path(str(config.get('image', 'map.pgm')))
    if not image_path.is_absolute():
        image_path = map_yaml.parent / image_path
    width, height, pixels = read_pgm(image_path)
    resolution = float(config.get('resolution', 0.05))
    origin = config.get('origin', [0.0, 0.0, 0.0])
    origin_x, origin_y = float(origin[0]), float(origin[1])
    rectangles = occupied_rectangles(
        width,
        height,
        pixels,
        occupied_threshold=float(config.get('occupied_thresh', 0.65)),
        negate=bool(config.get('negate', 0)),
        min_cells=min_cells,
    )
    map_width = width * resolution
    map_height = height * resolution
    center_x = origin_x + map_width / 2.0
    center_y = origin_y + map_height / 2.0

    lines = [
        '<?xml version="1.0"?>',
        '<sdf version="1.9">',
        '  <world name="field">',
        '    <physics name="rover_physics" type="ignored">',
        '      <max_step_size>0.002</max_step_size>',
        '      <real_time_factor>1.0</real_time_factor>',
        '    </physics>',
        '    <plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>',
        '    <plugin filename="gz-sim-user-commands-system" name="gz::sim::systems::UserCommands"/>',
        '    <plugin filename="gz-sim-scene-broadcaster-system" name="gz::sim::systems::SceneBroadcaster"/>',
        '    <plugin filename="gz-sim-sensors-system" name="gz::sim::systems::Sensors"><render_engine>ogre2</render_engine></plugin>',
        '    <plugin filename="gz-sim-imu-system" name="gz::sim::systems::Imu"/>',
        '    <gravity>0 0 -9.81</gravity>',
        '    <light type="directional" name="sun">',
        '      <cast_shadows>true</cast_shadows>',
        '      <pose>0 0 10 0 0 0</pose>',
        '      <diffuse>0.8 0.8 0.8 1</diffuse>',
        '      <specular>0.2 0.2 0.2 1</specular>',
        '      <direction>-0.5 0.2 -0.9</direction>',
        '    </light>',
        '    <model name="field_floor">',
        '      <static>true</static>',
        f'      <pose>{center_x:.4f} {center_y:.4f} -0.05 0 0 0</pose>',
        '      <link name="floor">',
        f'        <collision name="collision"><geometry><box><size>{map_width:.4f} {map_height:.4f} 0.1</size></box></geometry></collision>',
        f'        <visual name="visual"><geometry><box><size>{map_width:.4f} {map_height:.4f} 0.1</size></box></geometry><material><ambient>0.48 0.50 0.46 1</ambient><diffuse>0.58 0.60 0.56 1</diffuse></material></visual>',
        '      </link>',
        '    </model>',
        f'    <!-- Generated from {escape(map_yaml.name)}; {len(rectangles)} occupied rectangles. -->',
        '    <model name="map_obstacles">',
        '      <static>true</static>',
        '      <link name="obstacles">',
    ]
    for index, (x0, x1, row0, row1) in enumerate(rectangles):
        size_x = (x1 - x0 + 1) * resolution
        size_y = (row1 - row0 + 1) * resolution
        center_cell_x = (x0 + x1 + 1) / 2.0
        center_cell_y = height - (row0 + row1 + 1) / 2.0
        x = origin_x + center_cell_x * resolution
        y = origin_y + center_cell_y * resolution
        pose = f'{x:.4f} {y:.4f} {wall_height / 2.0:.4f} 0 0 0'
        size = f'{size_x:.4f} {size_y:.4f} {wall_height:.4f}'
        lines.append(
            f'        <collision name="obstacle_{index}"><pose>{pose}</pose><geometry><box><size>{size}</size></box></geometry></collision>'
        )
        lines.append(
            f'        <visual name="obstacle_{index}_visual"><pose>{pose}</pose><geometry><box><size>{size}</size></box></geometry><material><ambient>0.18 0.20 0.22 1</ambient><diffuse>0.27 0.30 0.33 1</diffuse></material></visual>'
        )
    lines.extend(['      </link>', '    </model>'])

    if add_boundary:
        thickness = max(resolution, 0.05)
        west = origin_x - thickness / 2.0
        east = origin_x + map_width + thickness / 2.0
        south = origin_y - thickness / 2.0
        north = origin_y + map_height + thickness / 2.0
        lines.extend([
            '    <model name="map_boundaries">',
            '      <static>true</static>',
            '      <link name="boundaries">',
        ])
        boundaries = [
            ('west', west, center_y, thickness, map_height + 2 * thickness),
            ('east', east, center_y, thickness, map_height + 2 * thickness),
            ('south', center_x, south, map_width, thickness),
            ('north', center_x, north, map_width, thickness),
        ]
        for name, x, y, size_x, size_y in boundaries:
            pose = f'{x:.4f} {y:.4f} {wall_height / 2.0:.4f} 0 0 0'
            size = f'{size_x:.4f} {size_y:.4f} {wall_height:.4f}'
            lines.append(
                f'        <collision name="{name}"><pose>{pose}</pose><geometry><box><size>{size}</size></box></geometry></collision>'
            )
            lines.append(
                f'        <visual name="{name}_visual"><pose>{pose}</pose><geometry><box><size>{size}</size></box></geometry></visual>'
            )
        lines.extend(['      </link>', '    </model>'])

    lines.extend(['  </world>', '</sdf>', ''])
    return '\n'.join(lines), len(rectangles)


def parser() -> argparse.ArgumentParser:
    navigation_share = Path(get_package_share_directory('rover_navigation'))
    gazebo_share = Path(get_package_share_directory('rover_gazebo'))
    result = argparse.ArgumentParser(
        description='Convert a ROS PGM occupancy map into a Gazebo SDF world.',
    )
    result.add_argument(
        '--map', type=Path,
        default=navigation_share / 'maps' / 'current' / 'map.yaml',
    )
    result.add_argument(
        '--output', type=Path,
        default=gazebo_share / 'worlds' / 'field.sdf',
    )
    result.add_argument('--wall-height', type=float, default=0.70)
    result.add_argument('--min-cells', type=int, default=1)
    result.add_argument('--no-boundary', action='store_true')
    return result


def main() -> None:
    args = parser().parse_args()
    if args.wall_height <= 0.0:
        raise SystemExit('--wall-height must be positive')
    if args.min_cells <= 0:
        raise SystemExit('--min-cells must be positive')
    world, rectangle_count = render_world(
        args.map.expanduser().resolve(),
        wall_height=args.wall_height,
        min_cells=args.min_cells,
        add_boundary=not args.no_boundary,
    )
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(world, encoding='utf-8')
    print(f'Generated {output} with {rectangle_count} obstacle rectangles')


if __name__ == '__main__':
    main()
