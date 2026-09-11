# Home Assistant 补充说明

主文档见仓库根目录 [README.md](../README.md)。本文补充安装后的操作细节。

## 依赖顺序

1. Mosquitto（或其它 broker）+ HA **MQTT** 集成  
2. [Bridge](https://github.com/SFNFIH/espnow2mqtt-bridge) 已连接协调器串口  
3. 本集成已添加，**base topic** 与 Bridge 一致  
4. 子设备固件来自 [espnow2mqtt-firmware](https://github.com/SFNFIH/espnow2mqtt-firmware)

## 配对

```text
开发者工具 → 服务 → espnow2mqtt.permit_join
duration: 60
```

或：

```bash
mosquitto_pub -t espnow2mqtt/bridge/request/permit_join -m 60
```

窗口内给设备上电/复位。

## 控制载荷（`…/set`）

| 设备类型 | JSON 示例 |
|----------|-----------|
| 开关 | `{"switch":"ON"}` / `{"switch":"OFF"}` / `{"switch":"TOGGLE"}` |
| 灯 | `{"switch":"ON","brightness":180,"color_temp":300}` |
| 风扇 | `{"fan_mode":"auto","percentage":40}` |
| 窗帘 | `{"cover":"OPEN"}` / `{"cover":"CLOSE"}` / `{"position":50}` |
| 锁 | `{"lock":"LOCK"}` / `{"lock":"UNLOCK"}` |
| 温控 | `{"hvac_mode":"heat","target_temperature":22}` |

Cluster 风格（固件也认）：

```json
{"ep":1,"cluster":"on_off","command":"on"}
{"ep":1,"cluster":"level_control","command":"move_to_level","level":128}
{"ep":1,"cluster":"door_lock","command":"unlock"}
```

## 实体何时出现

Hub 订阅 `espnow2mqtt/+/state`。收到带 `caps` 的状态后，各 platform 的 discovery 回调会 `async_add_entities`。  
同一 MAC + key 只创建一次；之后只更新状态。
