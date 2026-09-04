from pathlib import Path

from rover_gazebo.map_to_world import occupied_rectangles, read_pgm, render_world


def test_occupied_rectangles_merges_identical_row_runs():
    pixels = [
        0, 0, 255, 255,
        0, 0, 255, 0,
        255, 255, 255, 0,
    ]

    rectangles = occupied_rectangles(
        4,
        3,
        pixels,
        occupied_threshold=0.65,
        negate=False,
        min_cells=1,
    )

    assert rectangles == [(0, 1, 0, 1), (3, 3, 1, 2)]


def test_render_world_reads_binary_map_and_places_obstacle(tmp_path: Path):
    image = tmp_path / 'map.pgm'
    image.write_bytes(b'P5\n3 2\n255\n' + bytes([0, 0, 255, 0, 0, 255]))
    config = tmp_path / 'map.yaml'
    config.write_text(
        'image: map.pgm\n'
        'resolution: 0.5\n'
        'origin: [-1.0, -2.0, 0.0]\n'
        'negate: 0\n'
        'occupied_thresh: 0.65\n'
        'free_thresh: 0.196\n',
        encoding='utf-8',
    )

    width, height, pixels = read_pgm(image)
    world, count = render_world(
        config,
        wall_height=0.7,
        min_cells=1,
        add_boundary=False,
    )

    assert (width, height, pixels) == (3, 2, [0, 0, 255, 0, 0, 255])
    assert count == 1
    assert '<size>1.0000 1.0000 0.7000</size>' in world
    assert '<pose>-0.5000 -1.5000 0.3500 0 0 0</pose>' in world
