"""Constants for ESP-NOW 2 MQTT integration."""

DOMAIN = "espnow2mqtt"
DEFAULT_BASE_TOPIC = "espnow2mqtt"
CONF_BASE_TOPIC = "base_topic"

ATTR_MAC = "mac"
ATTR_CAPS = "caps"
ATTR_HOP = "hop"
ATTR_VIA = "via"
ATTR_NODE_ROLE = "node_role"

# MQTT relative suffixes under base topic
TOPIC_BRIDGE_STATE = "bridge/state"
TOPIC_BRIDGE_DEVICES = "bridge/devices"
TOPIC_BRIDGE_INFO = "bridge/info"
TOPIC_PERMIT_JOIN = "bridge/request/permit_join"
