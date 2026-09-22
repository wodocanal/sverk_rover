# Camera Models

Russian operator/update guide: `docs/vision-markers.md` in the repository root.

## Default: YOLO11n COCO

`yolo11n.pt` and `yolo11n.yaml` replace the previous custom `best.pt`/`best.yaml`.
This is the official Ultralytics nano detector with 80 COCO classes (person,
bicycle, car, bottle, chair, etc.), not a model for the old custom classes.

- Source: https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt
- SHA-256: `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1`
- Documentation: https://docs.ultralytics.com/models/yolo11/
- Upstream licensing: AGPL-3.0 / Ultralytics Enterprise.
- Input: 320 x 320, selected in the manifest to reduce CPU work on Raspberry Pi.
  Smaller input can miss distant/small objects. Actual FPS depends on hardware;
  the configured FPS is an upper limit, not a performance guarantee.

Install `requirements.txt` in the Python environment running the ROS node.
The loader uses `ultralytics.YOLO`; class labels are read from the checkpoint.
Only load trusted checkpoints. Weights are included, so startup does not require
an automatic model download. A direct node run and both package configs select
`yolo11n` by default. Remove any custom launch override `model_name:=best`.

Supported runtime formats are `ultralytics_pt` and `opencv_ssd_tf`. Existing SSD
assets remain as an alternative; old ONNX assets are not selectable because
this runtime does not implement an ONNX backend. A new model needs a YAML
manifest; `.pt` models do not need a separate labels file.

## OpenCV ArUco and QR

On **Camera -> Video processing**, disable processing, choose **Recognize ArUco**
and/or **Recognize QR**, apply, then enable processing. Both flags default to
false and are ROS parameters `detect_aruco` and `detect_qr`. The markers are
detected on the original frame, separately from YOLO, without training a model.
The main processing switch still controls the whole pipeline.

`aruco_dictionary` defaults to `DICT_4X4_50`; select the dictionary matching your
printed markers. Standard 4x4, 5x5, 6x6, 7x7 families and ARUCO_ORIGINAL are
supported. OpenCV 4.6's `detectMarkers` and newer `ArucoDetector` APIs are handled.
The installed OpenCV must include `cv2.aruco`; the Ubuntu ROS image's
`python3-opencv` does. For other environments, verify the import first and use
an OpenCV build with ArUco support (do not mix several pip OpenCV variants).
QR uses `QRCodeDetector.detectAndDecodeMulti` with a single-code fallback.

Results go into `/detections` along with YOLO detections:

- `kind: object`: existing class_id, label, confidence, bbox, center.
- `kind: aruco`: marker_id, dictionary, corners, bbox, label.
- `kind: qr`: data (decoded text), decoded (boolean), corners, bbox, label.

`count` is the total; `object_count` and `marker_count` separate the categories.
There is no invented neural-network confidence for marker detections. Markers
are outlined in `/image_processed` and `/image_processed/compressed`; the web
list displays IDs and QR text safely, without opening URLs or executing content.
This is 2D recognition only, not calibrated pose/distance estimation.

Web edits remain runtime ROS parameters, like the existing detector settings.
For defaults after restart edit `config/vision.yaml`.
