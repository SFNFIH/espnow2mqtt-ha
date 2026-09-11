# 使用指南

装好之后怎么用：配对、自动化、模板、以及什么时候该绕过集成直接用 MQTT。

装的步骤在 [quickstart.md](quickstart.md)，实体的字段和换算在
[entities.md](entities.md)。

目录：

1. [配置项：只有一个 base topic](#1-配置项只有一个-base-topic)
2. [`permit_join` 服务](#2-permit_join-服务)
3. [控制设备](#3-控制设备)
4. [推荐的自动化](#4-推荐的自动化)
5. [在模板里取值](#5-在模板里取值)
6. [绕过集成直接用 MQTT](#6-绕过集成直接用-mqtt)
7. [命令的成败反馈](#7-命令的成败反馈)
8. [改设备名](#8-改设备名)
9. [彻底删掉一个设备](#9-彻底删掉一个设备)
10. [能源面板](#10-能源面板)
11. [多个协调器](#11-多个协调器)

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

> **一个 base topic 只能有一个 entry，但可以有多个 entry。**
> `unique_id` 是 `f"{DOMAIN}:{base}"`，所以重复添加同一个前缀会
> `already_configured`，而换个前缀就能再加一个协调器。
> 见 [§11](#11-多个协调器)。
>
> **0.3.x 里**`unique_id` 是写死的 `DOMAIN`，
> 一个 HA 实例**只能接一个协调器**。

添加集成时如果 HA 里还没配 MQTT，会直接 abort 并提示
"MQTT integration is not set up. Add MQTT first."
（`mqtt_not_ready`）。判定条件是"存在一个已经 LOADED 的 mqtt config
entry"，而不是 `mqtt` 这个组件有没有被 import——
后者因为 `manifest.json` 里声明了 `dependencies: ["mqtt"]` 而恒为真，
见 [architecture.md §8.5](architecture.md#85-一个协调器一个-entry)。

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

**这是最该做的一条。** 协调器一挂，所有设备实体会同时变 unavailable
（见 [entities.md §12.3](entities.md#123-这是判断整套系统死活的正确实体)），
所以**告警要挂在这一个实体上**，不然几十个设备会各推一条通知。

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

### 4.5 按键触发

按键是 `event` 实体，触发方式和别的实体不一样：
**监听它的状态变化，然后按 `event_type` 属性分支**。
`event` 实体的"状态"是事件发生的时间戳，所以每次按键都是一次
状态变化，不会被 HA 的去重吃掉。

```yaml
automation:
  - alias: 门铃按钮
    triggers:
      - trigger: state
        entity_id: event.doorbell_button
    conditions:
      # 过滤掉 HA 重启时的 unknown -> 时间戳
      - condition: template
        value_template: "{{ trigger.from_state.state not in ['unknown','unavailable'] }}"
    actions:
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ trigger.to_state.attributes.event_type == 'press' }}"
            sequence:
              - action: light.toggle
                target: {entity_id: light.hallway}
          - conditions:
              - condition: template
                value_template: "{{ trigger.to_state.attributes.event_type == 'double_press' }}"
            sequence:
              - action: scene.turn_on
                target: {entity_id: scene.all_off}
          - conditions:
              - condition: template
                value_template: "{{ trigger.to_state.attributes.event_type == 'long_press' }}"
            sequence:
              - action: notify.persistent_notification
                data: {message: 门铃被长按}
```

四种 `event_type`：`press`、`double_press`、`long_press`、`release`。
固件报的原话在 `attributes.action` 里，自增计数器在
`attributes.value` 里。换算规则和"为什么固件必须报计数器"见
[entities.md §11](entities.md#11-event按钮)。

> **0.3.x 里这件事只能绕开集成做**，用 `platform: mqtt` 直接订阅
> `espnow2mqtt/<slug>/state`——因为 `button` cap 不产生任何实体。
> 那种写法还有个隐患：`<slug>/state` 是 retained 的，
> HA 每次重启都会收到最后一条，于是**重启就响一次门铃**。

### 4.6 命令没送到时告警

见 [§7](#7-命令的成败反馈)。

---

## 5. 在模板里取值

大部分信息都有独立的实体（诊断量），另外每个设备实体身上
还挂了一组 `espnow2mqtt_*` 属性。

| 想要什么 | 怎么取 |
|---|---|
| 跳数 | `states('sensor.bedroom_sensor_mesh_hop')` |
| 节点角色 | `states('sensor.bedroom_sensor_node_role')` → `leaf` / `router` |
| RSSI | `states('sensor.bedroom_sensor_rssi')` |
| Bridge 在线 | `is_state('binary_sensor.esp_now_coordinator_bridge','on')` |
| 灯的亮度（HA 0–255） | `state_attr('light.living_room_light','brightness')` |
| 窗帘开度（HA 0–100） | `state_attr('cover.bedroom_cover','current_position')` |
| 协调器信道 | `state_attr('binary_sensor.esp_now_coordinator_bridge','channel')` |
| 协调器固件 | `state_attr('binary_sensor.esp_now_coordinator_bridge','fw')` |
| 设备总数 | `state_attr('binary_sensor.esp_now_coordinator_bridge','devices')` |

### 5.1 每个设备实体都带 `espnow2mqtt_*` 属性

`EspNowEntity.extra_state_attributes` 在**每一个**设备实体上
（light / switch / sensor / …，不含 Bridge 那个）都放了这些：

| 属性 | 什么时候有 | 内容 |
|---|---|---|
| `espnow2mqtt_mac` | 总是 | 设备 MAC；`slug:` 占位设备是 `None` |
| `espnow2mqtt_caps` | 总是 | 当前能力列表，可能是 `[]`（还没上报过） |
| `espnow2mqtt_hop` | `hop` 已知 | 跳数 |
| `espnow2mqtt_via` | `via` 已知 | **上一跳的 MAC** |
| `espnow2mqtt_node_role` | `node_role` 已知 | `leaf` / `router` |

所以上一跳直接这么取：

```jinja
{{ state_attr('switch.living_room_switch', 'espnow2mqtt_via') }}
```

列出所有经由某个 router 中继的设备：

```yaml
template:
  - sensor:
      - name: "经由 Router A 的设备"
        state: >
          {{ states.switch
             | selectattr('attributes.espnow2mqtt_via','defined')
             | selectattr('attributes.espnow2mqtt_via','eq','AA:BB:CC:00:11:22')
             | map(attribute='name') | list | join(', ') }}
```

看一个设备被推断出了哪些能力（排查"实体没出来"时很有用）：

```jinja
{{ state_attr('sensor.bedroom_sensor_temperature', 'espnow2mqtt_caps') }}
```

> **0.3.x 里这五个常量在 `const.py` 里定义好了，但没有任何代码用它们。**
> `hop` / `node_role` / `rssi` 有独立的诊断实体，
> 而 `via` 和 `caps` 在 HA 里**完全看不到**——
> 想知道上一跳只能自己配一个 `platform: mqtt` 的 sensor 去解
> `value_json.via`。

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
（见 [entities.md §1.3](entities.md#12-诊断实体总是有)）。

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

0.4.0 之后需要绕开集成的事情只剩三件：

| 想做什么 | 为什么集成做不到 |
|---|---|
| 移除设备（`unpair`） | Bridge 没有暴露 MQTT 入口，只能往串口发（[§9](#9-彻底删掉一个设备)） |
| 发 fire-and-forget 命令 | 集成总是让 Bridge 带 ACK/重传 |
| cluster 风格的命令（指定端点） | 集成只发扁平 payload（[§6.2](#62-手工发命令)） |

> **0.3.x 里这个表还有三行：按键事件、协调器信道/固件版本、设备的 `via`。**
> 现在分别有了 `event` 实体（[entities.md §11](entities.md#11-event按钮)）、
> Bridge 实体的属性（[entities.md §12.1](entities.md#121-协调器的自述都挂在这个实体的属性上)）、
> 和 `espnow2mqtt_via` 属性（[§5.1](#51-每个设备实体都带-espnow2mqtt_-属性)）。
> 如果你照着旧文档配过那几个 `platform: mqtt` sensor，
> **现在可以删掉了**，留着只是重复。

### 6.1 读原始状态

```yaml
mqtt:
  - sensor:
      name: "Doorbell Raw"
      state_topic: "espnow2mqtt/doorbell/state"
      value_template: "{{ value_json.button | default('none') }}"
```

`<slug>/state` 是 retained 的，所以这个 sensor 重启后立刻有值。

> 这个例子只用来看原始 payload。**真要做门铃自动化请用
> `event.doorbell_button`**——上面这个 sensor 因为主题是 retained 的，
> HA 每次重启都会重新收到最后一次按键，用它做触发会误触发。

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

## 7. 命令的成败反馈

`<slug>/set` 本身是 fire-and-forget 的：集成 publish 完就返回，
服务调用不会阻塞、也不会抛异常。
但命令的**结局**会沿着反方向走回来。

### 7.1 反馈链路

协调器对每条下行命令都会回一个 ack（成功，或者重传耗尽后的
`timeout` / `send_fail`）。Bridge 收到 ack 后把它重新发布到
**`<base>/<slug>/command_result`**（非 retained），
Hub 订阅这个主题，成功的只记一条 debug 日志，
失败的则在 HA 的事件总线上 fire 一个 **`espnow2mqtt_command_failed`**。

```
light.turn_on
  → espnow2mqtt/living_room/set   {"switch":"ON"}
  → USB  {"type":"cmd","id":7,...}
  → ESP-NOW（最多 4 次发送，1.6 s 窗口）
  ← USB  {"type":"ack","id":7,"ok":false,"error":"timeout"}
  ← espnow2mqtt/living_room/command_result
         {"id":7,"ok":false,"mac":"AA:...","error":"timeout",
          "payload":{"switch":"ON"},"elapsed_ms":1642}
  ← HA 事件总线：espnow2mqtt_command_failed
```

`command_result` 的字段：

| 字段 | 总是有 | 内容 |
|---|---|---|
| `id` | ✓ | 命令序号，和 Bridge 日志里的那个是同一个 |
| `ok` | ✓ | `true` / `false` |
| `mac` | ✓ | 目标 MAC，认不出来时是 `null` |
| `error` | 失败时 | `timeout` / `send_fail` / … |
| `payload` | Bridge 还记得这条命令时 | **原始命令内容**，用来判断是哪个操作失败了 |
| `elapsed_ms` | 同上 | 从 publish 到 ack 的耗时 |

`payload` 和 `elapsed_ms` 来自 Bridge 的 `pending` 表。
那个表有 30 秒 TTL（`PENDING_TTL_S`），所以协调器中途重启、
ack 迟到太久的话这两个字段会缺失，但 `id` / `ok` / `error` 还在。

### 7.2 `espnow2mqtt_command_failed` 事件

事件数据：

| 键 | 内容 |
|---|---|
| `entry_id` | 哪个 config entry（多协调器时用得上） |
| `slug` | 设备的 MQTT slug |
| `mac` | 设备 MAC，占位设备或认不出来时是 `None` |
| `name` | 设备名（固件报的那个），可能是 `""` |
| `id` | 命令序号 |
| `error` | `timeout` / `send_fail` / … |
| `payload` | 原始命令内容，可能是 `None` |

**只有失败才会 fire。** 成功的命令不产生事件——
否则一个正常的家庭每天会有几千个事件塞满 logbook。

一条通用的告警自动化：

```yaml
automation:
  - alias: ESP-NOW 命令失败告警
    triggers:
      - trigger: event
        event_type: espnow2mqtt_command_failed
    actions:
      - action: notify.persistent_notification
        data:
          title: ESP-NOW 命令没送到
          message: >
            {{ trigger.event.data.name or trigger.event.data.slug }}
            未响应命令 #{{ trigger.event.data.id }}
            （{{ trigger.event.data.error }}）。
            内容：{{ trigger.event.data.payload }}
```

按错误类型分开处理：

```yaml
automation:
  - alias: ESP-NOW 重试超时的命令
    triggers:
      - trigger: event
        event_type: espnow2mqtt_command_failed
        event_data:
          error: timeout
    actions:
      # 只重试一次，而且只重试开关类命令
      - condition: template
        value_template: "{{ 'switch' in (trigger.event.data.payload or {}) }}"
      - action: mqtt.publish
        data:
          topic: "espnow2mqtt/{{ trigger.event.data.slug }}/set"
          payload: "{{ trigger.event.data.payload | to_json }}"
```

> **⚠️ 自动重试要小心。** `timeout` 的常见原因是设备断电或者
> 信号太差，这两种情况重试也不会成功，只会让 ESP-NOW 信道更忙。
> 上面那条自动化没有次数上限，真要用得加一个 `input_number` 计数器。
> 更稳的做法是**只告警不重试**。

> **0.3.x 里协调器的 ack 到了 Bridge 就停下了**，只写一行日志：
>
> ```
> WARNING espnow2mqtt: command 7 to AA:BB:CC:DD:EE:FF failed: timeout
> ```
>
> MQTT 上没有任何反馈主题，HA 完全不知道命令失败过。
> 唯一能察觉的办法是"发完等 5 秒，看实体状态变没变"（见 §7.3），
> 而这个办法对没有可读状态的命令（比如 `identify`）完全无效。

### 7.3 事件不能完全替代状态校验

`command_result` 说的是**"协调器把帧送到了设备并收到了链路层 ACK"**，
不是"设备照办了"。这两件事有区别：

| HA 里的表现 | `command_result` | 原因 |
|---|---|---|
| 状态不变 | `ok: false` | 命令根本没送到（断电 / 信号差） |
| 状态不变 | **`ok: true`** | 送到了，但设备**拒绝**了那个值（超出范围、cluster 没注册 identify 回调…） |
| 状态短暂变了又回去 | `ok: true` | HA 前端的乐观更新，被真实上报纠正 |

第二行是事件抓不到的。所以关键操作还是要校验状态：

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
      - wait_template: "{{ is_state('light.living_room_light','on') }}"
        timeout: "00:00:05"
        continue_on_timeout: true
      - if:
          - condition: state
            entity_id: light.living_room_light
            state: "off"
        then:
          - action: notify.persistent_notification
            data:
              message: 客厅灯没开成，检查设备
```

`wait_template` 比固定 `delay` 好：正常情况下 1 秒内状态就回来了，
不用干等 5 秒。5 秒的上限是有余量的——S3 侧的 ACK/重传窗口是
1.6 秒（4 次发送 + 超时），加上设备上报和 MQTT 的往返。

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

## 9. 彻底删掉一个设备

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

### 集成自己会删的那一种

有一种删除是自动的，和上面四步无关：**`slug:` 占位设备被合并掉时**。

设备的 retained `<slug>/state` 先到、`bridge/devices` 后到的情况下，
Hub 会先建一个 `slug:<name>` 的临时设备，等真 MAC 到了再把状态搬过去、
然后发 `SIGNAL_DEVICE_REMOVED` 把占位的删掉：

```python
@callback
def _device_removed(entry_id: str, mac: str) -> None:
    if entry_id != entry.entry_id:
        return
    hub.discovered = {
        uid for uid in hub.discovered if not uid.startswith(f"{mac}_")
    }
    registry = dr.async_get(hass)
    device = registry.async_get_device(identifiers={(DOMAIN, mac)})
    if device and entry.entry_id in device.config_entries:
        registry.async_update_device(
            device.id, remove_config_entry_id=entry.entry_id
        )
```

删设备注册表条目会连带删掉它下面的所有实体，这正是想要的——
占位设备下的每个实体的 `unique_id` 都是
`slug:xxx_<key>` 这种没法用的形式。

> **0.3.x 里这个合并根本不发生。** 占位设备和真设备会**同时存在**，
> 同一个物理设备在 HA 里出现两次：一个有完整状态但 MAC 显示不出来，
> 一个有 MAC 但状态是空的。只能手工删，而且删完下次 HA 重启还会再来一遍。
> 详见 [state-flow.md §3.3](state-flow.md#33-slug-占位设备)。

另一种自动删除是**能力消失时实体自删**（不是删设备），
见 [state-flow.md §6](state-flow.md#6-实体能增也能减)。

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

## 11. 多个协调器

一个 ESP-NOW 网络最多 32 个 peer，而且所有节点必须在同一个 Wi-Fi 信道上。
超出这个规模、或者想把两栋楼/两个楼层分开，就要跑第二个协调器。

**每个协调器 = 一个 Bridge 进程 + 一个独立的 base topic + 一个 config entry。**

### 11.1 配起来

1. 第二个 S3 烧同样的协调器固件，**信道设成不同的**
   （同信道的两个协调器会互相干扰配网）
2. 第二个 Bridge 进程指向不同的串口和不同的前缀：

```bash
espnow2mqtt --port /dev/ttyACM1 \
            --base-topic espnow2mqtt_upstairs \
            --state-file /var/lib/espnow2mqtt/devices-upstairs.json
```

**`--state-file` 一定要分开**，两个进程共用一个会互相覆盖。

3. HA 里再添加一次集成，base topic 填 `espnow2mqtt_upstairs`

`unique_id` 是 `f"{DOMAIN}:{base}"`，所以只要前缀不同就能加进去；
前缀相同会 `already_configured`。选项流里也做了同样的检查：
把 entry A 的前缀改成 entry B 已经在用的那个会报
"另一个 entry 已经在用这个主题"。

> **0.3.x 里加不了第二个。** `unique_id = DOMAIN` 加上
> `_async_current_entries()` 检查，第二次添加一定是
> `single_instance_allowed`。想接两个协调器只能开两个 HA 实例，
> 或者自己改 `config_flow.py`。

### 11.2 每个 entry 是完全独立的

| | |
|---|---|
| Hub 实例 | 各一个，`hass.data[DOMAIN][entry_id]` 分开存 |
| MQTT 订阅 | 各 6 个，前缀不同 |
| 设备表 | 完全隔离，同一个 MAC 在两个 entry 下是两个设备 |
| Bridge 实体 | **各一个**，`unique_id` 是 `f"{entry_id}_bridge"` |
| 协调器设备（设备注册表） | **共用一个**，`identifiers={(DOMAIN,"bridge")}` 是写死的 |

最后一行是个已知的粗糙之处：两个 entry 的 Bridge 实体会挂在
同一个"ESP-NOW Coordinator"设备下面。功能上没问题
（两个实体的 `unique_id` 不同，`base_topic` 属性能区分是哪个），
只是设备页上会看到两个 `Bridge` 实体。要分开得把
`identifiers` 改成带 `entry_id`，代价是老用户的设备条目会断开重建。

### 11.3 `permit_join` 会对所有协调器生效

```python
async def _permit_join(call: ServiceCall) -> None:
    duration = int(call.data.get(ATTR_DURATION, 60))
    for h in hass.data[DOMAIN].values():
        if isinstance(h, EspNowHub):
            await h.async_permit_join(duration)
```

服务**没有 target 参数**，所以调一次会把**每个**协调器的配网窗口都打开。

多协调器场景下这不是你想要的：新设备会连到先响应的那个协调器上，
不一定是你想要的那个。要精确控制就直接发 MQTT：

```yaml
action: mqtt.publish
data:
  topic: espnow2mqtt_upstairs/bridge/request/permit_join
  payload: "120"
```

或者只在想配网的那一刻临时停掉另一个 Bridge 进程。

### 11.4 区分实体属于哪个协调器

每个设备实体的 `espnow2mqtt_mac` 属性不带前缀信息，
但 Bridge 实体的 `base_topic` 属性有。
命令失败事件里也带了 `entry_id`：

```yaml
automation:
  - alias: 楼上协调器命令失败
    triggers:
      - trigger: event
        event_type: espnow2mqtt_command_failed
    conditions:
      - condition: template
        value_template: "{{ 'upstairs' in trigger.event.data.slug }}"
    actions: ...
```

更可靠的办法是按 `entry_id` 过滤，但 `entry_id` 是随机字符串，
得先去 `.storage/core.config_entries` 里查出来。
实践中按设备区域（area）分组比按协调器分组更好用。

---

## 相关文档

- [quickstart.md](quickstart.md) — 安装和第一次跑通
- [entities.md](entities.md) — 每个实体的字段、单位换算、已知限制
- [state-flow.md](state-flow.md) — 命令和状态的完整路径
- [architecture.md](architecture.md) — 集成的分层和配置流
- [troubleshooting.md](troubleshooting.md) — 按症状排查
- [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) — 全部 MQTT 主题
- [device 仓库 docs/data-model.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/data-model.md) — cluster 风格命令的全部参数
