# rover_camera

USB/V4L2-камера на OpenCV. Публикует raw/JPEG и отдаёт кадр через ROS-сервис.

## Запуск и параметры

```bash
ros2 launch rover_camera camera.launch.py
ros2 launch rover_camera camera.launch.py fps:=15.0 rotate:=180
```

Рабочий файл [config/camera.yaml](config/camera.yaml): `/dev/video0`,
1280x720, 30 FPS, MJPEG, JPEG quality 85, поворот 180 градусов.
Это запрошенные настройки, не гарантия поддержки камерой.
Проверяйте доступ пользователя к /dev/video*, OpenCV и V4L2. Утилита
`v4l2-ctl` из v4l-utils нужна для дополнительных сведений/настройки камеры в вебе.

## Интерфейсы

- `/image_raw`: sensor_msgs/Image.
- `/image_raw/compressed`: sensor_msgs/CompressedImage.
- `/get_frame`: rover_interfaces/srv/GetFrame.
- Frame ID: `camera_optical_frame`.

Захват и JPEG-кодирование разделены; используется latest-frame и
best-effort depth 1, чтобы медленный клиент не накапливал очередь.
Веб запрашивает свежие кадры с ограничением числа запросов, пропуская старые.
Это уменьшает задержку, но не гарантирует нулевой latency.

Не запускайте вторую ноду поверх уже работающей камеры. При изменении
настроек через веб ROS-параметры не становятся автоматически постоянными:
правьте camera.yaml для следующего старта и применяйте по
[правилам обновления](../../../docs/operations.md).

Распознавание выполняет отдельный [rover_vision](../../system/rover_vision/README.md),
сама камера не запускает YOLO.
