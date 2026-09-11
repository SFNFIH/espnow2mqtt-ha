# ESP-NOW 2 MQTT — Home Assistant Integration

Config-flow integration (ESPHome-like): devices appear automatically, **no entity YAML**.

Requires:
1. MQTT integration in Home Assistant
2. Running bridge: https://github.com/SFNFIH/espnow2mqtt-bridge
3. Flashed coordinator/devices: https://github.com/SFNFIH/espnow2mqtt-firmware

## Install

**HACS:** add custom repository `SFNFIH/espnow2mqtt-ha` (type Integration), install, restart.

**Manual:**

```bash
cp -r custom_components/espnow2mqtt /config/custom_components/
```

Then: **Settings → Devices & Services → Add Integration → ESP-NOW 2 MQTT**.

## Usage

- Service `espnow2mqtt.permit_join` opens pairing on the USB coordinator
- Entities are created from device `caps` (temperature, switch, contact, …)

See `docs/homeassistant.md`.
