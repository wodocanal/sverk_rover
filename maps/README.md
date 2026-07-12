# Rover Maps

Put Nav2-compatible map files here. The web interface reads `*.yaml` files from
this directory and uses the referenced image as the visualization background.

Typical structure:

```yaml
image: room.pgm
mode: trinary
resolution: 0.05
origin: [0.0, 0.0, 0.0]
negate: 0
occupied_thresh: 0.65
free_thresh: 0.196
```

`resolution` is meters per image pixel. For example, `0.05` means one map pixel
is 5 cm, so 10 cm of odometry movement is drawn as two map pixels.
