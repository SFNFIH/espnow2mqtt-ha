# ESP-NOW 2 MQTT — Home Assistant 插件

**本仓库 = Home Assistant 自定义集成（插件）。**  
Config Flow，设备自动出实体，**不用写实体 YAML**。

另外两个仓库：

| 仓库 | 内容 |
|------|------|
| [espnow2mqtt-host](https://github.com/SFNFIH/espnow2mqtt-host) | **ESP32-S3** 协调器固件 + USB↔MQTT Bridge |
| [espnow2mqtt-device](https://github.com/SFNFIH/espnow2mqtt-device) | **ESP32-C3** 设备 / 路由固件 |

总览：[espnow2mqtt](https://github.com/SFNFIH/espnow2mqtt)

---

## 文档

完整文档在 **[`docs/`](docs/)**。按需求找：

| 我想…… | 看这篇 |
|------|------|
| 装上并跑通（含前置条件检查） | [docs/quickstart.md](docs/quickstart.md) |
| 搞懂集成的分层、Hub、dispatcher 信号 | [docs/architecture.md](docs/architecture.md) |
| 搞懂一条 MQTT 消息怎么变成实体状态、实体怎么被创建 | [docs/state-flow.md](docs/state-flow.md) |
| 查 `caps` → 平台的映射、每个实体的字段和单位换算 | [docs/entities.md](docs/entities.md) |
| 查服务、自动化写法、模板取值 | [docs/usage.md](docs/usage.md) |
| 实体没出来 / 状态不更新 / 控制没反应 | [docs/troubleshooting.md](docs/troubleshooting.md) |
| 查 MQTT 主题和 payload | [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) |

文档索引和推荐阅读路线：**[docs/README.md](docs/README.md)**

---

## 安装前准备

1. HA 已配置 **MQTT**（如 Mosquitto）
2. 已烧录并插入 S3，且 [host 仓库](https://github.com/SFNFIH/espnow2mqtt-host) 的 Bridge 在跑
3. Bridge 的 `--base-topic` 与本集成一致（默认 `espnow2mqtt`）

---

## 安装

### HACS

自定义仓库添加 `SFNFIH/espnow2mqtt-ha` → Integration → 安装 → 重启。

### 手动

```bash
cp -r custom_components/espnow2mqtt /config/custom_components/
```

重启后：**设置 → 设备与服务 → 添加集成 → ESP-NOW 2 MQTT**。

---

## 配对

1. 确认 Bridge 在线（集成里有 Bridge 连通实体）
2. 服务 `espnow2mqtt.permit_join`（`duration` 秒）
3. 给 [device 仓库](https://github.com/SFNFIH/espnow2mqtt-device) 烧好的 C3 上电/复位

---

## 实体（由固件 `caps` 决定）

| Cap | 平台 |
|-----|------|
| `switch` | Switch |
| `light` | Light（亮度/色温） |
| `fan` / `cover` / `lock` / `climate` | 同名平台 |
| `temperature` `humidity` `pressure` `illuminance` `power` `energy` | Sensor |
| `contact` `occupancy` `motion` `smoke` `carbon_monoxide` | Binary sensor |
| `button` | Event（按键事件） |
| — | Sensor（诊断）：跳数、节点角色、RSSI，**每个设备都有** |

全表和每个字段的换算见 [docs/entities.md](docs/entities.md)。

能力消失时对应的实体会自己删掉，能力回来还会重建。

控制走 MQTT `espnow2mqtt/<slug>/set`，例如：

```json
{"switch":"ON"}
{"switch":"ON","brightness":200,"color_temp":300}
{"cover":"OPEN"}
{"lock":"UNLOCK"}
{"hvac_mode":"heat","target_temperature":22}
```

命令的结局会回到 `espnow2mqtt/<slug>/command_result`；失败时集成会在 HA
事件总线上 fire 一个 `espnow2mqtt_command_failed`，可以直接拿来配告警。
见 [docs/usage.md §7](docs/usage.md#7-命令的成败反馈)。

---

## 目录

```
custom_components/espnow2mqtt/
  __init__.py  config_flow.py  const.py
  hub.py  entity.py  discovery.py
  switch.py light.py fan.py cover.py lock.py climate.py
  sensor.py binary_sensor.py event.py
  manifest.json services.yaml translations/
tests/                 # pytest-homeassistant-custom-component
```

跑测试：

```bash
pip install -r requirements_test.txt
pytest tests/
```

更多：[docs/homeassistant.md](docs/homeassistant.md)

---

## License

MIT
