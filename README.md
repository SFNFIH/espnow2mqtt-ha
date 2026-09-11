# ESP-NOW 2 MQTT — Home Assistant Integration

Config-flow integration: devices appear automatically, **no entity YAML**.

Requires:
1. MQTT in Home Assistant
2. Bridge: https://github.com/SFNFIH/espnow2mqtt-bridge
3. Firmware (`en2m` interaction layer + your drivers): https://github.com/SFNFIH/espnow2mqtt-firmware

## Install

**HACS:** custom repo `SFNFIH/espnow2mqtt-ha` → Integration → install → restart.

**Manual:**

```bash
cp -r custom_components/espnow2mqtt /config/custom_components/
```

Then: **Settings → Devices & Services → Add Integration → ESP-NOW 2 MQTT**.

## Usage

- Service `espnow2mqtt.permit_join` opens pairing
- Entities follow device `caps` / cluster reports from firmware

See `docs/homeassistant.md`.
