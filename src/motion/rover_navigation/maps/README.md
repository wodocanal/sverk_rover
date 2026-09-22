# Rover maps

- `current/` is the map used by default by Nav2.
- `archive/` contains previous map versions.
- `map.yaml` and its image are used by Nav2 Map Server and AMCL.
- `map.posegraph` and `map.data` are used by SLAM Toolbox to continue mapping.

Save a map while SLAM is running:

```bash
ros2 run rover_navigation rover_map save room
```

The command updates the source project and synchronizes the installed current
map so navigation can be launched immediately without rebuilding.

`ROVER_MAPS_ROOT` may select an external writable maps root containing current
and archive. In that mode save does not synchronize installed maps: pass the
external map path to standalone Nav2 (the web uses its configured maps_root).
The web's `maps_root` points to the **current** directory, whereas the environment
variable names its **parent**. Set the same intended location for CLI and web.

Choosing an archive in the web selector passes that YAML to Nav2 without
overwriting current. `rover_map use <archive_directory_name>` does activate it
as current. Occupancy-only maps work for localization/navigation but cannot
resume SLAM without posegraph/data. Back up both current and archive before
updates; do not discard scanned maps to make `git pull` succeed.
