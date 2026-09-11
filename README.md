# ESP-NOW 2 MQTT — Home Assistant Integration

Config-flow integration: devices appear automatically, **no entity YAML**.

Requires:
1. MQTT in Home Assistant
2. Bridge: https://github.com/SFNFIH/espnow2mqtt-bridge
3. Firmware (`en2m` clusters + your drivers): https://github.com/SFNFIH/espnow2mqtt-firmware

## Install

**HACS:** custom repo `SFNFIH/espnow2mqtt-ha` → Integration → install → restart.

**Manual:**

```bash
cp -r custom_components/espnow2mqtt /config/custom_components/
```

Then: **Settings → Devices & Services → Add Integration → ESP-NOW 2 MQTT**.

## Platforms (from device `caps`)

| Cap | HA platform |
|-----|-------------|
| `switch` | Switch |
| `light` | Light (brightness / color temp) |
| `fan` | Fan |
| `cover` | Cover |
| `lock` | Lock |
| `climate` | Climate |
| `temperature` / `humidity` / `pressure` / `illuminance` / `power` / `energy` | Sensor |
| `contact` / `occupancy` / `motion` / `smoke` / `carbon_monoxide` | Binary sensor |

## Usage

- Service `espnow2mqtt.permit_join` opens pairing
- Entities follow firmware `caps` + state JSON

See `docs/homeassistant.md`.
