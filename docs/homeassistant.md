# Home Assistant 补充说明

主文档见 [README.md](../README.md)。

## 依赖的另外两个仓库

1. [espnow2mqtt-host](https://github.com/SFNFIH/espnow2mqtt-host) — S3 协调器 + Bridge  
2. [espnow2mqtt-device](https://github.com/SFNFIH/espnow2mqtt-device) — C3 设备固件  

## 配对

```text
开发者工具 → 服务 → espnow2mqtt.permit_join
duration: 60
```

或：

```bash
mosquitto_pub -t espnow2mqtt/bridge/request/permit_join -m 60
```

## 控制示例（`…/set`）

| 类型 | JSON |
|------|------|
| 开关 | `{"switch":"ON"}` |
| 灯 | `{"switch":"ON","brightness":180,"color_temp":300}` |
| 风扇 | `{"fan_mode":"auto","percentage":40}` |
| 窗帘 | `{"cover":"OPEN"}` / `{"position":50}` |
| 锁 | `{"lock":"UNLOCK"}` |
| 温控 | `{"hvac_mode":"heat","target_temperature":22}` |
