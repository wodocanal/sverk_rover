from pathlib import Path

import cv2
import numpy as np

from rover_vision.path_clearance import RoadAppearanceModel, TemporalDecision


ROI = [0.30, 0.15, 0.70, 0.15, 0.85, 0.95, 0.15, 0.95]


def road_frame(with_obstacle: bool = False) -> np.ndarray:
    frame = np.full((360, 480, 3), (125, 125, 125), dtype=np.uint8)
    cv2.rectangle(frame, (225, 30), (255, 330), (235, 235, 235), -1)
    if with_obstacle:
        cv2.rectangle(frame, (150, 150), (330, 280), (20, 30, 190), -1)
        cv2.rectangle(frame, (165, 170), (315, 195), (20, 20, 20), -1)
    return frame


def test_clear_calibration_frame_is_clear():
    model = RoadAppearanceModel(ROI)
    model.fit([road_frame() for _ in range(4)])

    metrics, _warped, _mask = model.analyze(road_frame())

    assert not metrics.blocked
    assert metrics.anomaly_fraction < 0.05


def test_large_object_crossing_corridor_is_blocked():
    model = RoadAppearanceModel(ROI)
    model.fit([road_frame() for _ in range(4)])

    metrics, _warped, _mask = model.analyze(road_frame(with_obstacle=True))

    assert metrics.blocked
    assert metrics.largest_component_fraction > 0.025


def test_model_round_trip(tmp_path: Path):
    model = RoadAppearanceModel(ROI)
    model.fit([road_frame() for _ in range(4)])
    path = tmp_path / 'road_model.npz'
    model.save(path)

    loaded = RoadAppearanceModel.load(path)
    metrics, _warped, _mask = loaded.analyze(road_frame())

    assert not metrics.blocked


def test_temporal_decision_requires_multiple_votes():
    decision = TemporalDecision(window_size=5, blocked_votes=3, clear_votes=4)

    assert decision.update(True) == 'unknown'
    assert decision.update(False) == 'unknown'
    assert decision.update(True) == 'unknown'
    assert decision.update(True) == 'blocked'
