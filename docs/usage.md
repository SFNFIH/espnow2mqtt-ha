# 使用指南

装好之后怎么用：配对、自动化、模板、以及什么时候该绕过集成直接用 MQTT。

装的步骤在 [quickstart.md](quickstart.md)，实体的字段和换算在
[entities.md](entities.md)。

目录：

1. [配置项：只有一个 base topic](#1-配置项只有一个-base-topic)
2. [`permit_join` 服务](#2-permit_join-服务)
3. [控制设备](#3-控制设备)
4. [推荐的自动化](#4-推荐的自动化)
5. [模板取值](#5-模板取值)
6. [绕过集成直接用 MQTT](#6-绕过集成直接用-mqtt)
7. [命令是单向的](#7-命令是单向的)
8. [改设备名](#8-改设备名)
9. [移除设备](#9-移除设备)
10. [能源面板](#10-能源面板)

---

## 1. 配置项：只有一个 base topic

集成只有**一个**配置项：MQTT 主题前缀。

**Settings → Devices & Services → ESP-NOW 2 MQTT → Configure**

| | |
|---|---|
| 默认值 | `espnow2mqtt` |
| 处理 | 输入时 `.strip().rstrip("/")`，所以 `espnow2mqtt/` 和 `espnow2mqtt` 等价 |
| 必须和谁一致 | **Bridge 的 `--base-topic`** |

改了会**整个重载 config entry**（`_async_update_listener` → `async_reload`）：
退订旧主题、丢掉整个内存设备表、用新前缀重新订阅。
实体会短暂不可用，然后随着新前缀下的 retained 消息重新填充。

> **只能添加一个集成实例。** config flow 里有
> `_async_current_entries()` 检查和 `unique_id = DOMAIN`，
> 双重保证。所以一个 HA 实例接不了两个协调器。
> 原因和改法见 [architecture.md §8.5](architecture.md#85-只允许一个-entry)。

添加集成时如果 HA 里还没配 MQTT，会直接 abort 并提示
"MQTT integration is not set up. Add MQTT first."
（`mqtt_not_ready`）。

---

## 2. `permit_join` 服务

**这是新设备入网的唯一入口。**

### 2.1 在 UI 里调

**Developer Tools → Actions（旧版叫 Services）→ `espnow2mqtt.permit_join`**

```yaml
action: espnow2mqtt.permit_join
data:
  duration: 120
```

| 参数 | 类型 | 默认 | 范围 |
|---|---|---|---|
| `duration` | int | `60` | **1–300** 秒 |

`services.yaml` 里声明了 number selector，所以 UI 里是个滑条。
范围校验在三个地方都做了：voluptuous schema（`vol.Range(1, 300)`）、
`hub.async_permit_join` 的 `max(1, min(300, ...))`、以及 S3 固件侧。

### 2.2 它做了什么

```python
async def async_permit_join(self, seconds: int = 60) -> None:
    seconds = max(1, min(300, int(seconds)))
    await mqtt.async_publish(
        self.hass, f"{self.base}/bridge/request/permit_join", str(seconds), 0, False
    )
```

发一条**裸数字字符串**（`"120"`）到
`<base>/bridge/request/permit_join`，QoS 0，**不 retain**。

之后的链路：Bridge 转成 USB 上的 `{"type":"pair","seconds":120}`，
S3 调 `en2m_set_pairing(true)` 并记下截止时间。

**没有任何反馈。** 服务调用立刻返回，集成不知道配网有没有真的打开。
要确认，看 Bridge 的日志（应该有 `coord: pairing_enabled`）。

### 2.3 配对流程

1. 确认 `binary_sensor.*_bridge` 是 **on**（Bridge 在线）
2. 调 `espnow2mqtt.permit_join`，`duration: 120`
3. 给烧好的 C3 上电或复位
4. 几秒内 HA 里应该出现新设备

设备不出现，按顺序排查：
[troubleshooting.md §2](troubleshooting.md#2-新设备不出现)。

### 2.4 加一个"配对"按钮到仪表盘

```yaml
type: button
name: 配对新设备（2 分钟）
icon: mdi:plus-network
tap_action:
  action: perform-action
  perform_action: espnow2mqtt.permit_join
  data:
    duration: 120
```

---

## 3. 控制设备

**用标准的 HA 服务，不要手写 MQTT。** 集成会做单位换算
（尤其是窗帘的位置反转和灯的 0–254/0–255）。

```yaml
# 开关
action: switch.turn_on
target: {entity_id: switch.living_room_switch}

# 灯：亮度 + 色温
action: light.turn_on
target: {entity_id: light.living_room_light}
data:
  brightness: 200          # HA 的 0–255
  color_temp_kelvin: 3000

# 亮度按百分比（HA 会自己换算成 0–255）
action: light.turn_on
target: {entity_id: light.living_room_light}
data:
  brightness_pct: 60

# 窗帘开到 30%（HA 语义：30% = 开了三成）
action: cover.set_cover_position
target: {entity_id: cover.bedroom_cover}
data:
  position: 30

# 风扇
action: fan.set_percentage
target: {entity_id: fan.ceiling_fan}
data:
  percentage: 60

action: fan.set_preset_mode
target: {entity_id: fan.ceiling_fan}
data:
  preset_mode: auto        # off / low / medium / high / on / auto / smart

# 门锁
action: lock.lock
target: {entity_id: lock.front_door}

# 温控器：先切模式，再设温度
action: climate.set_hvac_mode
target: {entity_id: climate.living_ac}
data:
  hvac_mode: cool

action: climate.set_temperature
target: {entity_id: climate.living_ac}
data:
  temperature: 24
```

> **温控器一定要先切模式再设温度。** 固件存了两个 setpoint
> （制热/制冷各一个），`target_temperature` 写的是"当前模式对应的那一个"。
> 在 `heat` 下设 24 °C 再切到 `cool`，目标温度会跳回制冷设定点的旧值。
> 见 [entities.md §10.3](entities.md#103-单个-setpoint)。

> **窗帘的位置在 HA 服务里是"开度"**，集成内部会转成固件的"关闭度"。
> 只有手工发 MQTT 时才需要自己 `100 - x`，见
> [§6](#6-绕过集成直接用-mqtt)。

---

## 4. 推荐的自动化

### 4.1 监控 Bridge 掉线

**这是最该做的一条。** 因为 Bridge 挂掉时**设备实体不会立刻变灰**
（见 [entities.md §11](entities.md#11-bridge-连通性实体)），
只有 Bridge 那个连通性实体会立刻变成 off。

```yaml
automation:
  - alias: ESP-NOW Bridge 掉线告警
    triggers:
      - trigger: state
        entity_id: binary_sensor.esp_now_coordinator_bridge
        from: "on"
        to: "off"
        for: "00:01:00"          # 抖动过滤，避免 HA 重启误报
    actions:
      - action: notify.persistent_notification
        data:
          title: ESP-NOW 协调器离线
          message: >
            Bridge 已离线超过 1 分钟。检查 USB 是否松了、Bridge 进程是否在跑。
```

`for: "00:01:00"` 很重要——HA 自己重启时这个实体会短暂变 off/unknown。

### 4.2 监控设备离线

设备的离线判定来自协调器（90 秒没收到任何帧），所以
`unavailable` 是可信的——**只要 Bridge 还在线**。

```yaml
automation:
  - alias: ESP-NOW 设备离线告警
    triggers:
      - trigger: state
        entity_id:
          - sensor.bedroom_sensor_temperature
          - switch.living_room_switch
        to: "unavailable"
        for: "00:05:00"
    conditions:
      # 只有 Bridge 在线时才告警，否则会对每个设备各报一次
      - condition: state
        entity_id: binary_sensor.esp_now_coordinator_bridge
        state: "on"
    actions:
      - action: notify.persistent_notification
        data:
          message: "{{ trigger.to_state.name }} 已离线 5 分钟"
```

那个 `condition` 是关键：Bridge 一挂所有设备都会变 unavailable，
不加条件的话 32 个设备会推 32 条通知。

### 4.3 监控信号质量

```yaml
automation:
  - alias: ESP-NOW 信号变差
    triggers:
      - trigger: numeric_state
        entity_id: sensor.bedroom_sensor_rssi
        below: -85
        for: "00:30:00"
    actions:
      - action: notify.persistent_notification
        data:
          message: >
            {{ trigger.to_state.name }} 的 RSSI 是
            {{ trigger.to_state.state }} dBm，已经在临界值以下半小时。
            考虑在中间加一个 router 节点。
```

RSSI 的参考值：> -60 很好，-60～-75 正常，-75～-85 临界，< -85 不可用。

RSSI 实体的刷新频率 = `bridge/devices` 的重写频率，
即**每个设备每 30 秒一次**。所以 `for: "00:30:00"` 大约是 60 个采样点。

### 4.4 跳数变化（拓扑变了）

```yaml
automation:
  - alias: ESP-NOW 拓扑变化
    triggers:
      - trigger: state
        entity_id: sensor.bedroom_sensor_mesh_hop
    conditions:
      - condition: template
        value_template: "{{ trigger.from_state.state not in ['unknown','unavailable'] }}"
      - condition: template
        value_template: "{{ trigger.to_state.state != trigger.from_state.state }}"
    actions:
      - action: logbook.log
        data:
          name: ESP-NOW
          message: >
            {{ trigger.to_state.name }} 跳数从
            {{ trigger.from_state.state }} 变成 {{ trigger.to_state.state }}
```

跳数从 1 变 2 意味着设备改挂到了一个 router 下面，
通常是直连信号变差了。

---

## 5. 模板取值

集成**不暴露 `hop` / `via` / `caps` 作为实体属性**——
所有信息都在独立的实体里。

| 想要什么 | 怎么取 |
|---|---|
| 跳数 | `states('sensor.bedroom_sensor_mesh_hop')` |
| 节点角色 | `states('sensor.bedroom_sensor_node_role')` → `leaf` / `router` |
| RSSI | `states('sensor.bedroom_sensor_rssi')` |
| Bridge 在线 | `is_state('binary_sensor.esp_now_coordinator_bridge','on')` |
| 灯的亮度（HA 0–255） | `state_attr('light.living_room_light','brightness')` |
| 窗帘开度（HA 0–100） | `state_attr('cover.bedroom_cover','current_cover_position')` |

### 5.1 `via`（上一跳）拿不到

`EspNowDevice.via` 在 Hub 里维护着，但**没有任何实体暴露它**。
要看只能直接读 MQTT：

```yaml
mqtt:
  - sensor:
      name: "Bedroom Sensor Via"
      state_topic: "espnow2mqtt/bedroom_sensor/state"
      value_template: "{{ value_json.via | default('unknown') }}"
      entity_category: diagnostic
```

同理，**协调器的信道和固件版本**也拿不到（`bridge_info` 从未被填充，
见 [architecture.md §3.4](architecture.md#34-没有订阅-bridgeinfo)）：

```yaml
mqtt:
  - sensor:
      name: "ESP-NOW Channel"
      state_topic: "espnow2mqtt/bridge/info"
      value_template: "{{ value_json.channel }}"
      entity_category: diagnostic
  - sensor:
      name: "ESP-NOW Coordinator FW"
      state_topic: "espnow2mqtt/bridge/info"
      value_template: "{{ value_json.fw }}"
      entity_category: diagnostic
```

这两个主题都是 retained 的，所以 HA 重启后立刻有值。

### 5.2 统计在线设备数

```yaml
template:
  - sensor:
      - name: "ESP-NOW 在线设备数"
        state: >
          {{ states.sensor
             | selectattr('entity_id','search','_mesh_hop$')
             | rejectattr('state','in',['unknown','unavailable'])
             | list | count }}
```

用 `Mesh Hop` 这个诊断实体来数，因为**每个设备都必然有一个**
（见 [entities.md §1.3](entities.md#13-诊断实体总是有)）。

更直接的办法是读 `bridge/devices`：

```yaml
mqtt:
  - sensor:
      name: "ESP-NOW 在线设备数"
      state_topic: "espnow2mqtt/bridge/devices"
      value_template: "{{ value_json | selectattr('online') | list | count }}"
  - sensor:
      name: "ESP-NOW 设备总数"
      state_topic: "espnow2mqtt/bridge/devices"
      value_template: "{{ value_json | count }}"
```

### 5.3 最弱信号的设备

```yaml
mqtt:
  - sensor:
      name: "ESP-NOW 最弱信号"
      state_topic: "espnow2mqtt/bridge/devices"
      unit_of_measurement: "dBm"
      value_template: >
        {% set online = value_json | selectattr('online')
                                   | rejectattr('rssi','none') | list %}
        {{ (online | map(attribute='rssi') | min) if online else 'unknown' }}
      json_attributes_topic: "espnow2mqtt/bridge/devices"
```

---

## 6. 绕过集成直接用 MQTT

集成有几个缺口需要直接用 MQTT 补：

| 想做什么 | 为什么集成做不到 |
|---|---|
| 按键事件 | `button` cap 不产生实体（[entities.md §1.1](entities.md#11-button-cap-不产生任何实体)） |
| 协调器信道 / 固件版本 | `bridge_info` 从未被填充 |
| 设备的 `via` | 没有实体暴露它 |
| 移除设备（`unpair`） | Bridge 没有暴露 MQTT 入口 |
| 发 fire-and-forget 命令 | 集成总是让 Bridge 带 ACK/重传 |

### 6.1 读原始状态

```yaml
mqtt:
  - sensor:
      name: "Doorbell Button"
      state_topic: "espnow2mqtt/doorbell/state"
      value_template: "{{ value_json.button | default('none') }}"
```

`<slug>/state` 是 retained 的，所以这个 sensor 重启后立刻有值。

`<slug>/<key>` 这些扁平主题**不 retain**，而且值是 Python 的 `str()`
（`True` 不是 `true`，列表是 `['a']` 不是 `["a"]`）——
**别用它们做权威数据源**，用 `<slug>/state`。
见 [host 仓库 docs/mqtt.md §9](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md#9-slugkey-扁平主题)。

### 6.2 手工发命令

```yaml
action: mqtt.publish
data:
  topic: espnow2mqtt/living_room/set
  payload: '{"switch":"ON","brightness":200}'
  # retain 一定不要开
```

**手工发命令时要注意两件事：**

1. **窗帘的位置是固件语义（0=开，100=关），和 HA 反着。**

   ```yaml
   # 想让窗帘开到 30%
   payload: '{"position":70}'    # 100 - 30
   ```

2. **亮度是固件的 0–254，不是 HA 的 0–255。**

   ```yaml
   payload: '{"switch":"ON","brightness":254}'   # 最亮
   ```

还可以用 cluster 风格的命令，指定端点（集成完全不支持这种写法）：

```yaml
action: mqtt.publish
data:
  topic: espnow2mqtt/living_room/set
  payload: '{"ep":2,"cluster":"on_off","command":"toggle"}'
```

`ep` 只有多端点设备才需要。全部 cluster / command / 参数在
[device 仓库 docs/data-model.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/data-model.md)。

### 6.3 让设备闪灯确认身份

```yaml
action: mqtt.publish
data:
  topic: espnow2mqtt/living_room/set
  payload: '{"identify":10}'
```

设备会执行 10 秒的 identify 效果（通常是闪灯）。
**前提是固件注册了 identify 回调**——大多数例程没注册，
那样这条命令会被静默忽略（设备仍然会 ACK）。

> **⚠️ 永远不要往 `<slug>/set` 发 retained 消息。**
> retained 的命令会在 Bridge 每次重连 MQTT 时重新投递，
> 于是"HA 重启就自动开灯"。清理：
>
> ```bash
> mosquitto_pub -t espnow2mqtt/living_room/set -r -n
> ```
>
> **规则：状态 retain，命令不 retain。**

---

## 7. 命令是单向的

**集成发出命令后不等任何确认。** `<slug>/set` 是单向的，
MQTT 上没有 `last_error` 之类的反馈主题。

完整链路里的失败会在 Bridge 的日志里出现：

```
WARNING espnow2mqtt: command 7 to AA:BB:CC:DD:EE:FF failed: timeout
WARNING espnow2mqtt: command 8 to AA:BB:CC:DD:EE:FF failed: send_fail
```

但**这些都不会到 MQTT，所以 HA 完全不知道**。

| HA 里的表现 | 可能的原因 |
|---|---|
| 实体状态不变 | 命令超时（设备断电/信号差）；或者设备收到了但**拒绝**了那个值 |
| 实体状态短暂变了又回去 | HA 前端的乐观更新，真实状态上报回来后被纠正 |

### 怎么察觉命令失败

**在自动化里加"验证 + 重试"**：

```yaml
automation:
  - alias: 确保灯真的开了
    triggers:
      - trigger: state
        entity_id: input_boolean.want_light_on
        to: "on"
    actions:
      - action: light.turn_on
        target: {entity_id: light.living_room_light}
      - delay: "00:00:05"
      - if:
          - condition: state
            entity_id: light.living_room_light
            state: "off"
        then:
          - action: light.turn_on
            target: {entity_id: light.living_room_light}
          - delay: "00:00:05"
          - if:
              - condition: state
                entity_id: light.living_room_light
                state: "off"
            then:
              - action: notify.persistent_notification
                data:
                  message: 客厅灯两次都没开成，检查设备
```

5 秒的延迟是有余量的：S3 侧的 ACK/重传窗口是 1.6 秒
（4 次发送 + 超时），加上设备上报和 MQTT 的往返，
正常情况 1 秒内状态就回来了。

### 要真正的失败反馈得改代码

Bridge 的 `_on_ack` 里加一次 publish（比如到
`<base>/<slug>/last_error`），集成再订阅它。两边都要改。
当前版本没有。

---

## 8. 改设备名

有两种"名字"，改法和影响完全不同。

### 8.1 改 HA 里的显示名（推荐）

**Settings → Devices & Services → espnow2mqtt → 点设备 → 齿轮 → 改名**

| 影响 | 说明 |
|---|---|
| HA 里的显示名 | ✓ 改了 |
| 实体 ID | 不变（除非你勾"同时重命名实体 ID"） |
| MQTT 主题 | **不变**。slug 来自固件的 `name` |
| 历史数据 | 保留 |

**这是最安全的改名方式。** 集成的 slug 和 HA 的显示名完全解耦。

### 8.2 改固件里的 `name`（会产生孤儿主题）

改 C3 固件的 `en2m_config_t.name` 重新烧：

| 影响 | 说明 |
|---|---|
| slug | **变了** → MQTT 主题全变 |
| 实体 | **不变**（`unique_id` 用的是 MAC，不是 slug） |
| 老主题 | **retained 消息还在，永远不再更新** |

所以 HA 里看起来一切正常，但 broker 上多了一堆孤儿主题。清理：

```bash
mosquitto_pub -t espnow2mqtt/old_name/state -r -n
mosquitto_pub -t espnow2mqtt/old_name/availability -r -n
```

不清也不会出错（集成会按新 slug 找设备），只是 broker 上有垃圾。
**但如果你曾经开过 Bridge 的 `--ha-discovery`，老的 discovery
config 主题会让 HA 里多出一套永远不可用的实体**，那就必须清。

> **想彻底避免这个问题：把固件里的 `name` 留空。**
> slug 就恒等于紧凑 MAC，永远不变。HA 里的显示名用 §8.1 的方式改。

---

## 9. 移除设备

要完整移除一个设备，四步都得做。**少做一步它就会回来。**

### 第 1 步：从协调器踢掉

**Bridge 没有暴露 MQTT 入口**，只能手工往串口发。
先停 Bridge（串口独占）：

```bash
sudo systemctl stop espnow2mqtt
printf '{"type":"unpair","mac":"AA:BB:CC:DD:EE:FF"}\n' > /dev/ttyACM0
sudo systemctl start espnow2mqtt
```

这会从 S3 的 peer 表和路由表里删掉它。
**但配网窗口开着的话它还能重新加入**，所以确认配网是关的。

### 第 2 步：断电或重刷设备

```bash
cd <device-repo>/examples/relay_switch
idf.py -p /dev/ttyACM1 erase-flash
```

`erase-flash` 会清掉 NVS（包括持久化的属性值和记住的父节点）。
不刷就断电，否则它会继续发心跳。

### 第 3 步：清 MQTT retained 消息

**这一步最容易漏。** 不清的话 HA 重启后设备会从 retained 消息里"复活"。

```bash
mosquitto_pub -t espnow2mqtt/relay1/state -r -n
mosquitto_pub -t espnow2mqtt/relay1/availability -r -n
```

顺手看看还有没有别的：

```bash
mosquitto_sub -t 'espnow2mqtt/relay1/#' -v --retained-only
```

`bridge/devices` 里那一项**不用管**——Bridge 会在下次重写时
把它去掉（前提是第 1 步做了）。实际上 Bridge 也不删
`self.devices` 里的条目，所以你可能还得：

```bash
sudo systemctl stop espnow2mqtt
# 编辑 devices.json 删掉那个 MAC，或者整个删掉让它重新学
sudo rm /var/lib/espnow2mqtt/devices.json
sudo systemctl start espnow2mqtt
```

### 第 4 步：从 HA 删除

**Settings → Devices & Services → espnow2mqtt → 点设备 → 齿轮 → 删除**

这会删掉设备和它的所有实体。

> **顺序很重要。** 如果你先删 HA 里的设备但没清 retained 消息，
> 下一条 `bridge/devices` 或 retained 的 `<slug>/state` 到达时
> 设备就又回来了——因为集成是按 MQTT 上的内容重建设备表的，
> 它根本不知道你在 HA 里删过。

---

## 10. 能源面板

`energy` sensor 的 `state_class` 是 `TOTAL_INCREASING`，
可以直接进 HA 的能源面板。

**Settings → Dashboards → Energy → Add device → 选
`sensor.smart_plug_energy`**

| | |
|---|---|
| 单位 | Wh（固件已经 ÷1000 换算过了） |
| 语义 | 单调递增的累计值。归零时 HA 自动当成一次重启处理 |
| 断电会归零吗 | **不会**。固件把 `ENERGY_MWH` 持久化到 NVS（见 [device 仓库 docs/persistence.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/persistence.md)） |
| 什么会归零 | 只有 `idf.py erase-flash` |

`power` sensor 是 `MEASUREMENT`（瞬时值），**不能**进能源面板的
"累计消耗"，但可以进"单个设备功率"的图表。

### 上报间隔会影响能源统计精度

叶子节点默认 30 秒上报一次（`EN2M_REPORT_INTERVAL_LEAF_MS`），
常电节点 15 秒。能源面板按小时聚合，30 秒的采样足够。

但如果你把上报间隔调得很长（比如 5 分钟省电），
能源曲线会变得很粗糙。调参见
[device 仓库 docs/kconfig.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/kconfig.md)。

---

## 相关文档

- [quickstart.md](quickstart.md) — 安装和第一次跑通
- [entities.md](entities.md) — 每个实体的字段、单位换算、已知限制
- [state-flow.md](state-flow.md) — 命令和状态的完整路径
- [architecture.md](architecture.md) — 集成的分层和配置流
- [troubleshooting.md](troubleshooting.md) — 按症状排查
- [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) — 全部 MQTT 主题
- [device 仓库 docs/data-model.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/data-model.md) — cluster 风格命令的全部参数
