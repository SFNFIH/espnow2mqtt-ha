# Home Assistant setup

1. Mosquitto + MQTT integration
2. Bridge: https://github.com/SFNFIH/espnow2mqtt-bridge
3. This integration (HACS or copy `custom_components/espnow2mqtt`)
4. Add integration in UI → `espnow2mqtt.permit_join`
5. Flash devices from https://github.com/SFNFIH/espnow2mqtt-firmware

## Entity discovery

Firmware state topics (`espnow2mqtt/<slug>/state`) publish JSON with:

- `caps`: list of capabilities (`light`, `fan`, `cover`, `lock`, `climate`, …)
- Flat fields: `switch`, `brightness`, `color_temp`, `percentage`, `position`, `lock`, `hvac_mode`, …

Commands go to `espnow2mqtt/<slug>/set` with the same flat keys, e.g.:

```json
{"switch":"ON","brightness":180,"color_temp":300}
{"cover":"OPEN"}
{"lock":"UNLOCK"}
{"fan_mode":"auto","percentage":40}
{"hvac_mode":"heat","target_temperature":22}
```

Matter-style cluster commands are also accepted by firmware:

```json
{"ep":1,"cluster":"on_off","command":"on"}
{"ep":1,"cluster":"level_control","command":"move_to_level","level":128}
```
