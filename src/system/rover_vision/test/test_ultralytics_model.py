from types import SimpleNamespace
from pathlib import Path

import numpy as np

from rover_vision.camera_detector_node import CameraDetectorNode
from rover_vision.model_registry import discover_model_manifests


def test_custom_pt_manifest_is_selectable():
    manifests = {
        item.identifier: item
        for item in discover_model_manifests(Path(__file__).parents[1] / 'models')
    }
    model = manifests['best']
    assert model.valid
    assert model.model_format == 'ultralytics_pt'
    assert model.model_path.name == 'best.pt'


def test_ultralytics_results_become_annotated_detections():
    class Values:
        def __init__(self, values):
            self.values = values

        def cpu(self):
            return self

        def tolist(self):
            return self.values

    class Detector:
        names = {0: 'left', 1: 'right'}

        def predict(self, **kwargs):
            assert kwargs['conf'] == 0.25
            assert kwargs['iou'] == 0.45
            boxes = SimpleNamespace(
                xyxy=Values([[1.2, 2.0, 8.9, 9.0]]),
                conf=Values([0.88]),
                cls=Values([1.0]),
            )
            return [SimpleNamespace(boxes=boxes, names=self.names)]

    node = SimpleNamespace(
        _detector=Detector(), confidence_threshold=0.25, nms_threshold=0.45,
        annotate_labels=True, annotate_confidence=True, line_thickness=2,
    )
    node._color_for_class = lambda class_id: CameraDetectorNode._color_for_class(node, class_id)
    node._annotate_detections = lambda frame, detections: CameraDetectorNode._annotate_detections(
        node, frame, detections
    )
    frame = np.zeros((12, 12, 3), dtype=np.uint8)
    annotated, detections = CameraDetectorNode._run_ultralytics_detection(node, frame)
    assert [(item.label, item.x, item.y, item.width, item.height) for item in detections] == [
        ('right', 1, 2, 8, 7),
    ]
    assert np.any(annotated != frame)
