# Home Assistant setup

1. Install Mosquitto + MQTT integration
2. Run bridge: https://github.com/SFNFIH/espnow2mqtt-bridge (Add-on or Docker)
3. Install this integration (HACS or copy `custom_components/espnow2mqtt`)
4. Add integration via UI → `espnow2mqtt.permit_join` → power on devices from https://github.com/SFNFIH/espnow2mqtt-firmware
