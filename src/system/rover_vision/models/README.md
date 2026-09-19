# Camera Models

В эту папку складываются модели и их manifest-файлы для `rover_vision`.

Поддерживаемые варианты:
- `OpenCV DNN` для TensorFlow SSD
- `Ultralytics YOLO` checkpoint в формате `.pt`
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

В рабочем дереве уже добавлены `best.pt` и `best.yaml` — дообученная модель
ровера. Файл весов имеет SHA-256
`e609e19448bf5c6f3678012fa7611b8030bd0b8fcc0343ef134a72d9aca47ef9`.

`.pt` не выполняется OpenCV напрямую. Для него нужен пакет `ultralytics` в том
же Python-окружении, из которого запускается `camera_detector_node`. Полный
список зависимостей лежит в `requirements.txt` пакета `rover_vision`.
Установка зависит от архитектуры Raspberry Pi и версии PyTorch, поэтому перед
запуском проверь импорт в окружении ROS: `python3 -c 'from ultralytics import YOLO'`.

Файлы ONNX в этой папке оставлены как материалы для будущего backend-а; текущая
нода не позволяет выбрать их, чтобы не создавать впечатление, что их вывод
проверен на ровере.
