# rover_vision

Обработка кадров камеры: детектор объектов YOLO, альтернативный OpenCV SSD,
опциональные ArUco/QR и публикация размеченного видео.

## Запуск и конфиг

```bash
ros2 launch rover_vision vision.launch.py
ros2 launch rover_vision vision.launch.py enabled:=true
```

Нужен работающий источник изображений. Конфиг:
[config/vision.yaml](config/vision.yaml). В full нода запускается, но
`enabled: false`: кнопку включения обработки предоставляет веб.

Пока обработка включена, параметры конвейера менять нельзя. Сначала выключите
обработку, примените параметры и включите обратно. Это переключение активности
внутри ROS-ноды: сама нода остаётся доступной для parameter services. Обработка
не зависит от открытого браузера. Runtime-правки не записывают YAML автоматически.

## Модели и зависимости

По умолчанию `yolo11n`, манифест и веса в [models](models).
Классы .pt читаются из checkpoint, поэтому новая дообученная модель может иметь
другие классы. Нужен совместимый YAML-манифест; не переименовывайте случайные
веса без проверки формата. Загружайте только доверенные checkpoints.

Установите [requirements.txt](requirements.txt) в Python-окружение процесса ROS.
Launch использует `PYTHONNOUSERSITE=1`: установка только в user site не является
достаточной. Нужен OpenCV с `cv2.aruco` и `QRCodeDetector`; не смешивайте
несколько сборок OpenCV в одном окружении. Фактический FPS зависит от CPU.

## Интерфейсы

| Направление | По умолчанию |
| --- | --- |
| Вход | `/image_raw`, sensor_msgs/Image |
| Видео | `/image_processed`, sensor_msgs/Image |
| JPEG | `/image_processed/compressed`, sensor_msgs/CompressedImage |
| Детекции | `/detections`, std_msgs/String с JSON |

`kind` различает object/aruco/qr, доступны bbox и подписи; рамки рисуются на
обработанном видео. Это 2D-детекция, не оценка расстояния/позы маркера.
Общие настройки: confidence/NMS, частота обработки, качество JPEG, словарь
ArUco, флаги `detect_aruco` и `detect_qr`.

[Полный операторский гайд](../../../docs/vision-markers.md).
[Форматы и лицензии моделей](models/README.md). MIT корня не заменяет лицензии весов.
