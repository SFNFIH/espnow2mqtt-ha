# 快速开始（HA 集成）

这一篇只管**集成侧**。它是链路的最后一环，所以**上游必须先跑通**。

跨三个仓库的完整流程在
[device 仓库 docs/quickstart.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/quickstart.md)。

---

## 0. 前置条件

装集成之前这三件事必须已经成立，否则装了也是空的：

| 条件 | 怎么确认 |
|---|---|
| **HA 里已配置 MQTT 集成** | Settings → Devices & Services 里有 MQTT 卡片 |
| **Bridge 在跑，而且能看到 S3** | `mosquitto_sub -t espnow2mqtt/bridge/info -C 1` 有内容 |
| **知道 Bridge 用的 base topic** | 默认 `espnow2mqtt` |

一条命令全查完：

```bash
mosquitto_sub -t 'espnow2mqtt/bridge/#' -v
```

期望（都是 retained，订上来立刻有）：

```
espnow2mqtt/bridge/state online
espnow2mqtt/bridge/info {"type":"hello","version":2,"role":"coordinator",...}
espnow2mqtt/bridge/devices []
```

| 结果 | 去哪 |
|---|---|
| 什么都没有 | Bridge 没跑，或前缀不是 `espnow2mqtt` → [host 仓库 quickstart](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/quickstart.md) |
| `bridge/state` 是 `online` 但 `bridge/info` **空** | Bridge 活着但收不到 S3 → [host 仓库 troubleshooting §2](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/troubleshooting.md#2-bridge-收不到-s3串口问题) |
| 三条都有 | **可以装集成了** |

> **`--ha-discovery` 必须是关的**（这是 Bridge 的默认值）。
> 它和本集成会产生两套重复实体。确认：
>
> ```bash
> mosquitto_sub -t 'homeassistant/+/espnow2mqtt_+/config' -v
> ```
>
> 有输出就说明 discovery 开着（或者留着老的 retained 消息），
> 见 [troubleshooting.md §6.7](troubleshooting.md#67-同一个设备有两套实体)。

---

## 1. 装集成

### 1.1 HACS（推荐）

1. **HACS → ⋮ → Custom repositories**
2. 仓库填 `SFNFIH/espnow2mqtt-ha`，类别选 **Integration**
3. 在 HACS 里搜 **ESP-NOW 2 MQTT** → Download
4. **重启 Home Assistant**

### 1.2 手动

```bash
git clone https://github.com/SFNFIH/espnow2mqtt-ha.git
cp -r espnow2mqtt-ha/custom_components/espnow2mqtt /config/custom_components/
```

确认拷全了：

```bash
ls /config/custom_components/espnow2mqtt/
# __init__.py binary_sensor.py climate.py config_flow.py const.py cover.py
# entity.py fan.py hub.py light.py lock.py manifest.json sensor.py
# services.yaml strings.json switch.py translations/
```

然后**重启 Home Assistant**。

> 自定义集成只在 HA 启动时加载，"重新加载配置"（Reload YAML）**不够**。
> 必须真的重启。

HA 最低版本 **2024.1.0**（`hacs.json` 里声明的）。
没有任何 Python 包依赖（`manifest.json` 里 `"requirements": []`）。

---

## 2. 添加集成

**Settings → Devices & Services → Add Integration → 搜 "ESP-NOW 2 MQTT"**

只有一个配置项：

| 字段 | 填什么 |
|---|---|
| **MQTT base topic** | **和 Bridge 的 `--base-topic` 一字不差**，默认 `espnow2mqtt` |

### 可能的 abort

| 提示 | 原因 | 解决 |
|---|---|---|
| "MQTT integration is not set up. Add MQTT first." | HA 里没有已加载的 MQTT config entry | 先加 MQTT 集成，并确认它连上了 broker |
| "ESP-NOW 2 MQTT is already configured" | **这个 base topic** 已经有 entry 了 | 想接第二个协调器就换一个前缀，见 [usage.md §11](usage.md#11-多个协调器) |

添加完不用重启——集成会立刻订阅并处理 retained 消息。

---

## 3. 验证

### 3.1 Bridge 连通性实体

**Settings → Devices & Services → ESP-NOW 2 MQTT → 应该看到一个设备
"ESP-NOW Coordinator"**，下面有一个实体：

```
binary_sensor.esp_now_coordinator_bridge     →  on（已连接）
```

| 它 | 含义 |
|---|---|
| **不存在** | 集成没加载成功 → [troubleshooting.md §1.2](troubleshooting.md#12-集成没装或没加载) |
| `off` | **base topic 不对**，或 Bridge 没跑 |
| `on` | **集成和 Bridge 通了** ✓ |

这个实体是无条件创建的，所以它一定存在。它是**判断整套系统死活的正确实体**
（见 [entities.md §12.3](entities.md#123-这是判断整套系统死活的正确实体)）。

### 3.2 已有的设备应该立刻出现

如果之前已经配对过设备，它们会**立刻**出现——集成靠 retained 消息重建状态，
不用等任何上报周期。

看不到就是上游 MQTT 上没有：

```bash
mosquitto_sub -t 'espnow2mqtt/+/state' -v
```

---

## 4. 加第一个设备

### 4.1 开配网窗口

**Developer Tools → Actions → `espnow2mqtt.permit_join`**

```yaml
action: espnow2mqtt.permit_join
data:
  duration: 120
```

`duration` 范围 1–300 秒，默认 60。

**这个服务没有任何反馈。** 要确认它生效了，去 Bridge 的日志看：

```
INFO espnow2mqtt: MQTT espnow2mqtt/bridge/request/permit_join => 120
INFO espnow2mqtt: coord: pairing_enabled
```

| 缺哪行 | 问题 |
|---|---|
| 第一行都没有 | **base topic 不一致** |
| 有第一行没第二行 | Bridge 到 S3 的串口链路有问题 |

服务在 Developer Tools 里找不到 = 集成没加载成功。

### 4.2 给 C3 上电

去 [espnow2mqtt-device](https://github.com/SFNFIH/espnow2mqtt-device)
烧一个例程（比如 `examples/relay_switch`），
**ESP-NOW 信道要和协调器一致**：

```bash
mosquitto_sub -t espnow2mqtt/bridge/info -C 1 \
  | python3 -c 'import json,sys; print("channel =", json.load(sys.stdin)["channel"])'
```

这个值必须等于设备固件的 `CONFIG_EN2M_WIFI_CHANNEL`。
**信道不匹配是"设备完全不上线"最常见的原因。**

### 4.3 期望看到

几秒内 HA 里出现一个新设备，比如 `relay1`，带：

```
switch.relay1_switch
sensor.relay1_mesh_hop        (diagnostic)
sensor.relay1_node_role       (diagnostic)
sensor.relay1_rssi            (diagnostic)
```

**实体是分两批建出来的**：三个诊断实体在 `bridge/devices` 到达时就建了，
功能实体（这里是 Switch）要等 `<slug>/state` 到达
——因为 `caps` 只从那里来。两者通常相隔几毫秒。

只出现诊断实体、没有功能实体，见
[troubleshooting.md §2.3](troubleshooting.md#23-只有诊断实体没有功能实体)。

---

## 5. 控制一下

```yaml
action: switch.turn_on
target:
  entity_id: switch.relay1_switch
```

或者直接在 HA 的 UI 里点那个开关。

**期望**：几百毫秒后实体状态变成 on。完整的往返是
HA → MQTT → Bridge → USB → S3 → 空口 → 设备执行 → ACK + 新状态 →
空口 → S3 → USB → Bridge → MQTT → HA。

**没反应**的排查顺序在
[troubleshooting.md §4](troubleshooting.md#4-控制没反应)。
最快的一步是监听 `espnow2mqtt/+/set` 看集成有没有真的发出去
（**Settings → Devices & Services → MQTT → Configure → Listen to a topic**）。

---

## 6. 接下来

### 按设备类型看会出什么实体

见 [entities.md §12](entities.md#13-按设备类型看会出什么)。
16 种设备类型都在那张表里。

### 加几个该有的自动化

**最该做的一条：监控 Bridge 掉线。**

因为 Bridge 挂掉时**设备实体不会立刻变灰**
（只有 Bridge 连通性实体会立刻变 off），所以：

```yaml
automation:
  - alias: ESP-NOW Bridge 掉线告警
    triggers:
      - trigger: state
        entity_id: binary_sensor.esp_now_coordinator_bridge
        from: "on"
        to: "off"
        for: "00:01:00"
    actions:
      - action: notify.persistent_notification
        data:
          title: ESP-NOW 协调器离线
          message: Bridge 已离线超过 1 分钟。
```

更多（设备离线、信号变差、拓扑变化）在
[usage.md §4](usage.md#4-推荐的自动化)。

### 智能插座接能源面板

`energy` sensor 的 `state_class` 是 `TOTAL_INCREASING`，
可以直接进能源面板：**Settings → Dashboards → Energy → Add device**。

见 [usage.md §10](usage.md#10-能源面板)。

### 搞懂内部实现

| 我想…… | 看这篇 |
|---|---|
| 搞懂 Hub / Entity / Platform 的分工 | [architecture.md](architecture.md) |
| 搞懂一条 MQTT 消息怎么变成实体状态 | [state-flow.md](state-flow.md) |
| 查每个实体读哪个字段、怎么换算 | [entities.md](entities.md) |
| 查服务、自动化、模板 | [usage.md](usage.md) |
| 出问题了 | [troubleshooting.md](troubleshooting.md) |

---

## 常见卡点速查

| 症状 | 最可能的原因 | 跳到 |
|---|---|---|
| 集成列表里搜不到 | 装完没重启 HA | [§1](#1-装集成) |
| 添加时提示 "MQTT integration is not set up" | 先加 MQTT 集成 | [§2](#2-添加集成) |
| `binary_sensor.*_bridge` 是 `off` | **base topic 不一致** | [troubleshooting.md §1.1](troubleshooting.md#11-base-topic-不一致最常见) |
| 集成装好了但一个设备都没有 | 上游 MQTT 上就没有 | [troubleshooting.md §2.1](troubleshooting.md#21-先确认-mqtt-上有没有) |
| 设备出现了但只有诊断实体 | `<slug>/state` 没到，或里面没有 `caps` | [troubleshooting.md §2.3](troubleshooting.md#23-只有诊断实体没有功能实体) |
| 新设备完全不出现 | **ESP-NOW 信道不匹配** | [§4.2](#42-给-c3-上电) |
| 所有实体都是灰的 | `bridge_online` 是 False | [troubleshooting.md §5.2](troubleshooting.md#52-全部实体都灰了) |
| 灯没有色温滑条 | 实体创建时 `color_temp` 还没到 → **重启 HA** | [troubleshooting.md §3.3](troubleshooting.md#33-灯没有色温滑条) |
| 窗帘开度是反的 | 手工发过未转换的 `position` | [entities.md §8.1](entities.md#81-位置的反转) |
| 实体名带 `_2` 后缀 | Bridge 的 `--ha-discovery` 也开着 | [troubleshooting.md §6.7](troubleshooting.md#67-同一个设备有两套实体) |
| 点了开关没反应 | 先看集成有没有发出 MQTT | [troubleshooting.md §4.1](troubleshooting.md#41-集成有没有发出去) |
