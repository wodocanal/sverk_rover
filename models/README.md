# Camera Models

В эту папку складываются модели и их manifest-файлы для `rover_vision`.

Поддерживаемый базовый сценарий сейчас:
- `OpenCV DNN`
- `ONNX`
- форматы манифестов `yolov5` и `yolov8`
- задача `detection`

Пример структуры:

```text
models/
  yolov8n.onnx
  yolov8n.yaml
```

Пример manifest:

```yaml
id: yolov8n
name: YOLOv8 Nano
description: Лёгкая модель для общих объектов
task: detection
format: yolov8
model: yolov8n.onnx
input_size: [640, 640]
swap_rb: true
confidence_threshold: 0.25
nms_threshold: 0.45
labels_file: coco.names
```

Если `labels_file` не указан, интерфейс всё равно заработает, но классы будут
показаны как `class_0`, `class_1` и так далее.
