# ESP-NOW 2 MQTT — Home Assistant 集成

Config Flow 自定义集成：设备上线后 **自动出现实体**，不需要为每个设备写 YAML。

依赖：

1. Home Assistant 内已配置好 **MQTT**（如 Mosquitto）
2. 主机上运行 [espnow2mqtt-bridge](https://github.com/SFNFIH/espnow2mqtt-bridge)（USB ↔ MQTT）
3. 子设备烧录 [espnow2mqtt-firmware](https://github.com/SFNFIH/espnow2mqtt-firmware)（`en2m` clusters）

总览：[espnow2mqtt](https://github.com/SFNFIH/espnow2mqtt)

---

## 安装

### 方式 A：HACS

1. HACS → 自定义仓库 → 添加 `SFNFIH/espnow2mqtt-ha`，类型选 **Integration**
2. 安装 **ESP-NOW 2 MQTT**
3. 重启 Home Assistant

### 方式 B：手动

```bash
cp -r custom_components/espnow2mqtt /config/custom_components/
```

重启 HA。

### 添加集成

**设置 → 设备与服务 → 添加集成 → ESP-NOW 2 MQTT**

配置项：

| 项 | 默认 | 说明 |
|----|------|------|
| Base topic | `espnow2mqtt` | 必须与 Bridge `--base-topic` 一致 |

集成依赖官方 MQTT 集成；请先保证 MQTT 能连上 broker。

---

## 配对设备

1. 确认 Bridge 在线（集成里会有 **Bridge** 连通性实体）
2. 开发者工具 → 服务，调用：

   - 服务：`espnow2mqtt.permit_join`
   - 参数：`duration`（秒，默认 60，最大 300）

   或 MQTT：

   ```bash
   mosquitto_pub -t espnow2mqtt/bridge/request/permit_join -m 60
   ```

3. 在配对窗口内给子设备上电 / 复位
4. 设备出现在 MQTT 设备列表后，集成按 `caps` 创建实体

---

## 实体与 `caps` 对应

固件 state JSON 中的 `caps` 决定创建哪些平台：

| Cap | HA 平台 | 说明 |
|-----|---------|------|
| `switch` | Switch | 纯 OnOff；若同时有 `light` 则 **不** 建 Switch |
| `light` | Light | 亮度（0–254→0–255）+ 可选色温（mireds↔Kelvin） |
| `fan` | Fan | `fan_mode` + `percentage` |
| `cover` | Cover | 固件 `position`：0=开…100=关；HA 显示为标准开合百分比 |
| `lock` | Lock | `LOCKED` / `UNLOCKED` |
| `climate` | Climate | `hvac_mode` + `target_temperature` + `current_temperature` |
| `temperature` | Sensor | °C |
| `humidity` | Sensor | % |
| `pressure` | Sensor | hPa |
| `illuminance` | Sensor | lux |
| `power` | Sensor | W |
| `energy` | Sensor | Wh |
| `contact` | Binary sensor | 门/窗 |
| `occupancy` | Binary sensor | 占用 |
| `motion` | Binary sensor | 运动（可与占用同源） |
| `smoke` | Binary sensor | 烟雾 |
| `carbon_monoxide` | Binary sensor | CO |

诊断类（几乎总会有）：

- Mesh Hop
- Node Role
- RSSI（有则显示）
- Bridge 连通性

---

## MQTT 约定

默认 base topic：`espnow2mqtt`。

| 主题 | 用途 |
|------|------|
| `espnow2mqtt/bridge/state` | Bridge `online` / `offline`（retain） |
| `espnow2mqtt/bridge/devices` | JSON 设备列表 |
| `espnow2mqtt/bridge/request/permit_join` | 开网秒数 |
| `espnow2mqtt/<slug>/state` | 设备状态 |
| `espnow2mqtt/<slug>/set` | 设备控制 |
| `espnow2mqtt/<slug>/availability` | 设备在线 |

`<slug>` 一般来自固件 `name`（空格变 `_`，小写），否则用 MAC。

### 状态示例

```json
{
  "caps": ["light"],
  "switch": "ON",
  "brightness": 200,
  "color_temp": 300,
  "node_role": "leaf"
}
```

### 控制示例（写到 `…/set`）

```json
{"switch":"ON","brightness":180,"color_temp":370}
{"cover":"CLOSE"}
{"position":40}
{"lock":"UNLOCK"}
{"fan_mode":"high","percentage":80}
{"hvac_mode":"heat","target_temperature":22}
```

集成内部通过 `hub.async_publish_set()` 发这些 JSON；也可手动用 `mosquitto_pub` 调试。

---

## 目录结构

```
custom_components/espnow2mqtt/
  __init__.py          # 加载平台、注册 permit_join
  config_flow.py       # UI 配置
  hub.py               # 订阅 MQTT、维护设备表
  entity.py            # 实体基类 / DeviceInfo
  switch.py / light.py / fan.py / cover.py / lock.py / climate.py
  sensor.py / binary_sensor.py
  const.py / services.yaml / manifest.json
  translations/
```

版本见 `manifest.json` 的 `version` 字段。

---

## 常见问题

**集成添加失败 / 无设备**  
- MQTT 集成是否正常？  
- Bridge 是否在线？主题 base 是否一致？  
- 是否执行过 `permit_join`？

**有 MQTT 消息但没有实体**  
- state 里是否带 `caps`？  
- 看 HA 日志 `custom_components.espnow2mqtt`  
- 灯类设备应有 `light`（带 brightness），不要只指望 `switch`

**控制无反应**  
- 确认发到 `espnow2mqtt/<slug>/set`  
- Bridge 串口是否连着协调器  
- 固件是否实现了对应 cluster 的 `set` 驱动

**窗帘方向反了**  
- 固件约定：`position` 0=开、100=关  
- HA Cover 标准：0=关、100=开（集成已做换算）

更多说明：[`docs/homeassistant.md`](docs/homeassistant.md)

---

## License

MIT
