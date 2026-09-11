# 状态流转

这一篇追踪**一条 MQTT 消息从到达到变成 HA 实体状态的完整路径**，
以及反方向的命令路径。

目录：

1. [两条方向](#1-两条方向)
2. [启动序列](#2-启动序列)
3. [上行：`<slug>/state` 的完整处理](#3-上行slugstate-的完整处理)
4. [上行：`bridge/devices`](#4-上行bridgedevices)
5. [上行：`<slug>/availability`](#5-上行slugavailability)
6. [实体只增不减](#6-实体只增不减)
7. [下行：从服务调用到 MQTT](#7-下行从服务调用到-mqtt)
8. [完整时序：新设备入网](#8-完整时序新设备入网)
9. [完整时序：一次开灯](#9-完整时序一次开灯)
10. [HA 重启后会发生什么](#10-ha-重启后会发生什么)

---

## 1. 两条方向

**上行（状态）**

```
MQTT 消息
  │
  ▼ HA mqtt 集成的回调（在事件循环上）
hub._on_device_state / _on_devices / _on_availability / _on_bridge_state
  │  修改 hub.devices[mac] 的字段
  ▼
async_dispatcher_send(SIGNAL_DEVICE_UPDATED, entry_id, mac)
  │  同步广播，所有订阅者串行执行
  ├─► 七个平台的 _discover(entry_id, mac)   → 可能 async_add_entities()
  └─► 所有 EspNowEntity._handle_update()    → mac 匹配则 async_write_ha_state()
```

**下行（命令）**

```
HA 服务调用（light.turn_on 等）
  │
  ▼ 平台实体的 async_turn_on / async_set_percentage / ...
拼出扁平 payload dict
  │
  ▼
hub.async_publish_set(device, payload)
  │
  ▼ mqtt.async_publish(topic=f"{base}/{slug}/set", json.dumps(payload), qos=0, retain=False)
MQTT
```

**两条方向完全解耦。** 命令发出去之后集成**不等任何确认**，
实体的状态只会因为上行的 `<slug>/state` 而改变。
这是标准的 MQTT 状态机语义，也意味着 UI 上会有一个来回的延迟
（命令 → 设备执行 → 设备上报 → Bridge 合并 → MQTT → 实体刷新，
通常几百毫秒）。

---

## 2. 启动序列

```
HA 启动 / 用户添加集成
  │
  ▼ __init__.py async_setup_entry
1. 算出 base topic（options → data → "espnow2mqtt"）
2. 建 EspNowHub，放进 hass.data[DOMAIN][entry_id]
3. await hub.async_start()              ← 建立 4 个 MQTT 订阅
      │
      │  ★ retained 消息开始涌入，此时平台还没起来
      │    bridge/state → bridge_online = True
      │    bridge/devices → 填满 hub.devices
      │    <slug>/state × N → 填 caps 和 state
      │    <slug>/availability × N → 填 online
      ▼
4. await async_forward_entry_setups(entry, PLATFORMS)
      │
      ▼ 七个平台各自 async_setup_entry
      4a. 注册 _discover 到 SIGNAL_DEVICE_UPDATED
      4b. for mac in list(hub.devices): _discover(entry_id, mac)
            └─► 这一步把第 3 步收到的所有设备都变成实体
5. 注册 espnow2mqtt.permit_join 服务（如果还没注册）
6. 挂上 options 更新监听器
```

**第 3 步和第 4 步的顺序是这个集成能"零配置自动出实体"的关键。**

订阅先建立，所以 retained 消息一定能收到。
平台后起来，所以它能一次性看到全部已知设备。
反过来（先起平台再订阅）会漏掉第一批 retained 消息，
用户就得等 30 秒才看到实体。

第 4b 步的 `list(hub.devices)` 做了一次拷贝——因为 `_discover`
在极端情况下可能间接导致 `hub.devices` 变化（实际不会，但拷贝是免费的保险）。

---

## 3. 上行：`<slug>/state` 的完整处理

这是整个集成最重的一个函数，逐段拆开看。

### 3.1 解析与过滤

```python
@callback
def _on_device_state(self, msg: mqtt.ReceiveMessage) -> None:
    parts = msg.topic.split("/")
    if len(parts) < 3 or parts[-1] != "state":
        return
    slug = parts[-2]
    if slug == "bridge":
        return
    raw = msg.payload
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(payload, dict):
        return
```

四道过滤，**任何一道不过就静默返回**：

| 检查 | 挡掉什么 |
|---|---|
| `len(parts) < 3 or parts[-1] != "state"` | 主题形状不对（防御性，通配符已经保证了） |
| `slug == "bridge"` | **`<base>/+/state` 也匹配 `<base>/bridge/state`** |
| `json.JSONDecodeError` | 非 JSON payload |
| `not isinstance(payload, dict)` | JSON 但不是对象（数组、数字、字符串） |

**全部静默**——没有任何日志。所以"状态不更新"这个症状在集成侧
很难看出原因，得去 MQTT 上看原始消息（见
[troubleshooting.md](troubleshooting.md#分诊mqtt-上有东西吗)）。

### 3.2 按 slug 找设备

```python
mac = None
for m, d in self.devices.items():
    if d.slug == slug:
        mac = m
        break
```

**线性扫描**，因为设备表是按 MAC 索引的，而主题里只有 slug。
设备数量是几十的量级，每条消息扫一遍无所谓。

### 3.3 `slug:` 占位设备

```python
if mac is None:
    # 合成一个无 MAC 的设备，等设备列表到达
    mac = f"slug:{slug}"
    self.devices[mac] = EspNowDevice(mac=mac, name=slug)
```

如果 `<slug>/state` 比 `bridge/devices` **先**到，集成还不知道这个 slug
对应哪个 MAC，于是建一个 key 为 `"slug:relay1"` 的占位设备。

这样做的好处是**不丢状态**：实体会被创建出来，能用，只是设备注册表里
的 `identifiers` 是 `(DOMAIN, "slug:relay1")` 而不是真 MAC
（`entity.py` 里也因此有 `not dev.mac.startswith("slug:")` 的判断，
避免给它加一条假的 MAC 连接）。

> **⚠️ 但占位设备永远不会和真设备合并**
>
> `_on_devices` 是按真 MAC 建/找对象的：
>
> ```python
> dev = self.devices.get(mac) or EspNowDevice(mac=mac)
> ```
>
> 它**不会**去找有没有同 slug 的 `slug:` 占位项，也不会删掉它。
> 所以一旦触发了这条路径，`hub.devices` 里会同时存在
> `"slug:relay1"` 和 `"AA:BB:CC:DD:EE:FF"` 两个对象，
> 而且它们的 `slug` 属性相同。后果：
>
> | 后果 | 说明 |
> |---|---|
> | **两套实体** | `slug:relay1_switch` 和 `AA:BB:...:FF_switch` 两个 unique_id |
> | 占位的那套会卡住 | 之后所有 `<slug>/state` 都会命中**第一个**匹配的（`for` 循环 `break`），dict 顺序决定是谁 |
> | HA 里两个设备 | 一个叫 `relay1`（来自占位），一个叫真名 |
>
> **实践中很少触发**，因为：
>
> 1. `bridge/devices` 的订阅在 `<base>/+/state` **之前**建立，
>    retained 消息按订阅顺序投递，所以启动时设备列表先到。
> 2. 新设备入网时，Bridge 的 `on_uplink` 先发 `device` 行
>    （→ 重写 `bridge/devices`）再发 `state` 行，顺序也是对的。
>
> 真要撞上，清理办法是**重启 HA**（`hub.devices` 是纯内存的，
> 重启后从 retained 消息重建，这次顺序是对的），
> 然后在 HA 里手工删掉那个多余的设备。

### 3.4 caps 推断：三级 fall-through

```python
caps = payload.get("caps")
if isinstance(caps, list):
    dev.caps = [str(c).lower() for c in caps]
elif isinstance(caps, str) and caps:
    dev.caps = [c.strip().lower() for c in caps.split(",") if c.strip()]
else:
    for key in ("temperature", "humidity", "pressure", "illuminance",
                "switch", "light", "contact", "occupancy", "motion",
                "smoke", "carbon_monoxide", "power", "energy",
                "fan", "cover", "lock", "climate",
                "brightness", "color_temp", "percentage", "position",
                "hvac_mode", "button"):
        if key in payload and key not in dev.caps:
            cap = {
                "brightness": "light",
                "color_temp": "light",
                "percentage": "fan",
                "fan_mode": "fan",
                "position": "cover",
                "hvac_mode": "climate",
                "target_temperature": "climate",
                "current_temperature": "climate",
            }.get(key, key)
            if cap not in dev.caps:
                dev.caps.append(cap)
```

| 级 | 依据 | 说明 |
|---|---|---|
| 1 | `caps` 是 JSON 数组 | 直接用，**整体替换** `dev.caps` |
| 2 | `caps` 是非空字符串 | 按逗号切（Bridge/设备为了省字节可能发 `"caps":"light"`） |
| 3 | 从 payload 的 key 推断 | **追加**到 `dev.caps`，不替换 |

注意级 1/2 是**替换**、级 3 是**追加**。所以一旦设备报过一次显式 `caps`，
那就是权威；之后某次上报把 `caps` 挤掉了（160 字节预算），会走级 3
在原有基础上追加——不会把已知能力擦掉。

> **映射字典里有三个死条目。** `"fan_mode"`、`"target_temperature"`、
> `"current_temperature"` 在映射表里，但**不在上面那个 `for` 的 key 元组里**，
> 所以永远不会被查到。
>
> 实际影响：一个只报 `{"fan_mode":"high"}` 而不报 `caps` 也不报
> `percentage` 的风扇，**不会被识别成 fan**。
> 正常的 `en2m` 固件总是报显式 `caps`，所以撞不上；
> 但如果你写第三方固件，记得带 `caps`。

`"light"` 也在 key 元组里，所以 payload 里出现字面上叫 `light` 的 key
会直接产生 `light` cap。`en2m` 不会发这个 key（它发 `switch` +
`brightness`），这是给第三方固件留的口子。

### 3.5 灯优先于开关

```python
if ("brightness" in payload or "color_temp" in payload or "level" in payload) \
        and "light" not in dev.caps:
    dev.caps.append("light")
if "light" in dev.caps and "switch" in dev.caps:
    dev.caps = [c for c in dev.caps if c != "switch"]
```

这段在级 1/2/3 **之后**无条件执行，所以即使设备报的是
`"caps":["switch"]`，只要 payload 里带了 `brightness`，
它也会被升级成灯。

两条规则：

1. 出现 `brightness` / `color_temp` / `level` ⇒ 加 `light` cap
   （注意 `level` 也算，这是给用 Matter 原始命名的固件留的兼容）
2. 同时有 `light` 和 `switch` ⇒ **删掉 `switch`**

第 2 条配合 `switch.py` 里的 `"switch" in dev.caps and "light" not in dev.caps`，
保证一个调光灯只出 **Light** 实体，不会同时出一个 Switch。
两个实体控制同一个设备会让 UI 和自动化都很混乱。

> **⚠️ 但如果 Switch 实体已经建好了，它不会被删**
>
> 场景：设备第一条上报只有 `{"switch":"ON"}`（亮度被 160 字节挤掉了），
> caps = `["switch"]` → **Switch 实体被创建**。
> 第二条上报带了 `brightness` → caps 变成 `["light"]` → **Light 实体被创建**。
>
> 结果：**同一个设备上同时有 `switch.x_switch` 和 `light.x_light`**。
> 两个都能用（都往同一个 `<slug>/set` 发命令），但状态会打架
> （Switch 只看 `switch` 字段，Light 也看 `switch` 字段，
> 所以其实两个显示是一致的，只是多了一个冗余实体）。
>
> 见 [§6](#6-实体只增不减)。处理办法是在 HA 里手工禁用/删除多余的实体。

### 3.6 拓扑字段

```python
if payload.get("node_role"):
    dev.node_role = str(payload["node_role"])
if "hop" in payload:
    try:
        dev.hop = int(payload["hop"])
    except (TypeError, ValueError):
        pass
if payload.get("via"):
    dev.via = str(payload["via"])
```

`hop` / `via` / `node_role` 在 `<slug>/state` 里是 Bridge/协调器注入的
（见 host 仓库 `docs/mqtt.md`）。

注意 **`rssi` 不在这里**——它只从 `bridge/devices` 来。

`node_role` 和 `via` 用的是 `payload.get(k)` 的真值判断，
所以空字符串不会覆盖已知值；`hop` 用的是 `in` 判断 + `try`，
所以 `null` 会被 `TypeError` 挡住。

### 3.7 合并与归一化

```python
merged = dict(dev.state)
merged.update(payload)
if "switch" in merged:
    sw = str(merged["switch"]).upper()
    merged["switch"] = "ON" if sw in ("ON", "1", "TRUE") else "OFF"
for binary_key in ("contact", "occupancy", "motion", "smoke", "carbon_monoxide"):
    if binary_key in merged:
        c = str(merged[binary_key]).upper()
        merged[binary_key] = "ON" if c in ("ON", "1", "TRUE", "OPEN", "DETECTED") else "OFF"
if "lock" in merged:
    lk = str(merged["lock"]).upper()
    merged["lock"] = "LOCKED" if lk in ("LOCKED", "LOCK", "1", "TRUE") else "UNLOCKED"
if "cover" in merged:
    cv = str(merged["cover"]).upper()
    if cv in ("CLOSED", "CLOSE"):
        merged["cover"] = "CLOSED"
    elif cv in ("OPEN", "OPENING"):
        merged["cover"] = "OPEN"
    else:
        merged["cover"] = cv
dev.state = merged
dev.online = True
```

**这是第二次合并。** Bridge 已经在它那边合并过一次了
（host 仓库 `docs/bridge.md §6.1`），集成又合一次。

为什么还要合？因为 Bridge 重启会丢 `last_state`，那时它发出的
`<slug>/state` 会比之前少几个字段。集成这一层的合并把那个坑填掉了——
**HA 侧的状态比 MQTT 上的 retained 消息更完整。**

代价和 Bridge 那边一样：**`dev.state` 只增不减**，
设备没法通过"不发某个字段"表达"这个字段消失了"。
`dev.state` 只在 HA 重启时清空。

### 3.8 归一化表

集成的归一化**比 Bridge 的更全**（Bridge 只处理 `switch` 和 `contact`）：

| 字段 | 认作"真"的输入（大小写无关） | 否则 |
|---|---|---|
| `switch` | `ON` / `1` / `TRUE` | `OFF` |
| `contact` | `ON` / `1` / `TRUE` / `OPEN` / **`DETECTED`** | `OFF` |
| `occupancy` | 同上 | `OFF` |
| `motion` | 同上 | `OFF` |
| `smoke` | 同上 | `OFF` |
| `carbon_monoxide` | 同上 | `OFF` |
| `lock` | `LOCKED` / **`LOCK`** / `1` / `TRUE` | `UNLOCKED` |
| `cover` | `CLOSED`/`CLOSE` → `CLOSED`；`OPEN`/`OPENING` → `OPEN` | **原值转大写**（比如 `STOP` 保持 `STOP`） |

`lock` 认 `LOCK` 是为了容忍"命令值被当成状态值回报"的固件；
`cover` 的 `else` 分支保留原值而不是强制成 `OPEN`/`CLOSED`，
这样 `cover.py` 的 `_closed_pct()` 兜底逻辑不会被误导。

**其他字段一律原样透传**：`brightness`、`color_temp`、`temperature`、
`percentage`、`position`、`hvac_mode`、`fan_mode`、`power`…… 都不归一化。
单位换算在实体层做（见 [entities.md](entities.md)）。

### 3.9 收到状态 ⇒ 在线

```python
dev.online = True
```

无条件。和 Bridge 的逻辑一致：能收到状态说明设备活着。

**集成自己不做超时判定**，`online` 变 `False` 只有一个来源：
`<slug>/availability` 上的 `offline`（最终来自协调器的 90 秒超时）。

### 3.10 派发

```python
async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac)
```

一条状态消息 → 一次派发 → 七个平台的 `_discover` + 所有实体的
`_handle_update` 串行执行。

---

## 4. 上行：`bridge/devices`

```python
lst = json.loads(raw)          # 必须是 list，否则 return
for item in lst:
    if not isinstance(item, dict): continue
    mac = str(item.get("mac") or "")
    if not mac: continue
    dev = self.devices.get(mac) or EspNowDevice(mac=mac)
    if item.get("name"):      dev.name = str(item["name"])
    if item.get("model"):     dev.model = str(item["model"])
    if "online" in item:      dev.online = bool(item["online"])
    if item.get("node_role"): dev.node_role = str(item["node_role"])
    if item.get("via"):       dev.via = str(item["via"])
    if "hop" in item and item["hop"] is not None:
        try: dev.hop = int(item["hop"])
        except (TypeError, ValueError): pass
    if "rssi" in item and item["rssi"] is not None:
        try: dev.rssi = int(item["rssi"])
        except (TypeError, ValueError): pass
    self.devices[mac] = dev
    async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac)
```

几个要点：

| 要点 | 说明 |
|---|---|
| **不处理 `caps` 和 `state`** | 那两个只从 `<slug>/state` 来。`bridge/devices` 里也没有这两个字段 |
| **`rssi` 只从这里来** | 这是唯一的 RSSI 来源 |
| **`online` 会被覆盖** | `if "online" in item: dev.online = bool(item["online"])`。Bridge 的设备列表里 `online` 是权威的 |
| **每个元素派发一次信号** | 32 个设备 = 32 次派发 × 7 个平台。Bridge 每 30 s 重写一次这个主题，所以这是集成里最重的周期性开销 |
| **不删除消失的设备** | 数组里没有的设备会留在 `hub.devices` 里。Bridge 那边也不删，所以实际上不会消失 |

> **性能提示**：32 个设备时，每 30 秒会有一次
> 32 × (7 个 `_discover` + 全部实体的 `_handle_update`) 的派发风暴。
> 每个 `_discover` 都因为 `uid in known` 立刻返回，
> `_handle_update` 也因为 MAC 不匹配立刻返回，所以单次开销极小。
> 但如果你有几百个设备，这里会成为瓶颈——那时应该改成
> "只对真正变化的设备派发"。

---

## 5. 上行：`<slug>/availability`

```python
@callback
def _on_availability(self, msg: mqtt.ReceiveMessage) -> None:
    parts = msg.topic.split("/")
    if len(parts) < 3:
        return
    slug = parts[-2]
    raw = msg.payload
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="ignore")
    online = str(raw).strip().lower() == "online"
    for mac, dev in self.devices.items():
        if dev.slug == slug:
            dev.online = online
            async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac)
            return
```

**注意这里不会创建占位设备。** 如果 availability 先到而设备表还没有这个 slug，
循环找不到就什么都不做。这是对的——availability 不携带任何状态，
为它建一个空设备没有意义。

`online` 的判断是严格的 `== "online"`，所以任何其他值（包括空 payload）
都会被当成离线。空 retained 消息（`mosquitto_pub -r -n`）会让设备变离线。

`return` 在循环里——**只更新第一个匹配的设备**。正常情况下 slug 是唯一的，
但如果触发了 `slug:` 占位问题（[§3.3](#33-slug-占位设备)），
就只有其中一个会被更新。

---

## 6. 实体只增不减

这是集成最明显的一个设计缺口，值得单独一节。

### 6.1 机制

每个平台的 `_discover` 里：

```python
known: set[str] = set()          # 闭包变量，在 async_setup_entry 里
...
uid = f"{mac}_{cap}"
if uid in known:
    return
known.add(uid)
async_add_entities([...])
```

**只有 `async_add_entities`，没有任何地方调用实体的 `async_remove()`。**

### 6.2 后果

| 场景 | 后果 |
|---|---|
| 设备的 `caps` 里丢掉了一个能力（换固件、或者 160 字节挤掉了） | 对应实体**永远留着**，状态停在最后已知值 |
| 设备先被识别成 switch 后被识别成 light | **两个实体都在**（[§3.5](#35-灯优先于开关)） |
| 设备被 `unpair` 了 | 设备和实体都留在 HA 里，变成不可用 |
| `slug:` 占位问题 | 两套实体 |

### 6.3 为什么这样设计还算可以接受

因为 `caps` 在 Hub 里是**只增不减**的（级 3 是 append，级 1/2 是替换但
只在显式 `caps` 到达时发生），而正常设备的能力集是固定的。
所以在正常使用下这个问题不会出现。

而且"实体不会自己消失"对 HA 用户来说其实是个好性质——
自动化引用的实体突然消失比一个不可用的实体更难排查。

### 6.4 怎么清理

手工。**Settings → Devices & Services → espnow2mqtt → 找到设备 → 
点多余的实体 → 齿轮 → 删除**。

如果整个设备都不要了：先在 HA 里删除设备，然后确保 MQTT 上没有
retained 的 `<slug>/state` 和 `<slug>/availability`
（否则下次 HA 重启它又会回来）：

```bash
mosquitto_pub -t espnow2mqtt/old_name/state -r -n
mosquitto_pub -t espnow2mqtt/old_name/availability -r -n
```

---

## 7. 下行：从服务调用到 MQTT

所有平台最终都汇到一个函数：

```python
async def async_publish_set(self, device: EspNowDevice, payload: dict) -> None:
    await mqtt.async_publish(
        self.hass,
        f"{self.base}/{device.slug}/set",
        json.dumps(payload),
        0,          # QoS 0
        False,      # retain=False
    )
```

| 参数 | 值 | 为什么 |
|---|---|---|
| 主题 | `<base>/<slug>/set` | Bridge 订阅的 `<base>/+/set` |
| payload | `json.dumps(payload)` | 扁平的 HA 风格 JSON |
| QoS | 0 | 命令丢了用户会再点一次；QoS 1 的去重开销不值得 |
| retain | **False** | **关键**。retained 的命令会在每次重连时重放 → "HA 重启就自动开灯" |

`async_set_switch` 是个便利包装：

```python
async def async_set_switch(self, device, value: str) -> None:
    await self.async_publish_set(device, {"switch": value})
```

只有 `switch.py` 用它。其他平台都直接调 `async_publish_set`,
因为它们要发多字段 payload。

### 每个平台发什么

完整表在 [entities.md](entities.md)，这里只列一眼能看懂的：

| HA 操作 | 发出的 JSON |
|---|---|
| `switch.turn_on` | `{"switch":"ON"}` |
| `light.turn_on`（带亮度） | `{"switch":"ON","brightness":<0-254>}` |
| `light.turn_on`（带色温） | `{"switch":"ON","color_temp":<mired>}` |
| `fan.turn_off` | `{"fan_mode":"off","percentage":0}` |
| `fan.set_percentage(50)` | `{"percentage":50,"fan_mode":"on"}` |
| `cover.open_cover` | `{"cover":"OPEN"}` |
| `cover.set_cover_position(30)` | `{"position":70}` ← **反转！** |
| `lock.lock` | `{"lock":"LOCK"}` |
| `climate.set_temperature(22)` | `{"target_temperature":22.0}` |

### `permit_join` 服务

```python
async def async_permit_join(self, seconds: int = 60) -> None:
    seconds = max(1, min(300, int(seconds)))
    await mqtt.async_publish(
        self.hass, f"{self.base}/{TOPIC_PERMIT_JOIN}", str(seconds), 0, False
    )
```

发的是**裸数字字符串**（比如 `"60"`），不是 JSON。
Bridge 两种都认（host 仓库 `docs/mqtt.md §5`）。

`max(1, min(300, ...))` 在集成侧夹了一次，S3 侧还会再夹一次。
双重保险。

---

## 8. 完整时序：新设备入网

```
用户：开发者工具 → 服务 → espnow2mqtt.permit_join {duration: 120}
  │
  ▼ hub.async_permit_join(120)
MQTT ← espnow2mqtt/bridge/request/permit_join = "120"   (retain=False)
  │
  ▼ Bridge._on_mqtt_message
USB  ← {"type":"pair","seconds":120}
  │
  ▼ S3 handle_host_line → en2m_set_pairing(true)
USB  → {"type":"log","msg":"pairing_enabled","seconds":120}
  │
  ▼ Bridge 记日志（不进 MQTT）

─── 用户给 C3 上电 ───

C3：收到 beacon → 选父节点 → 发 HELLO 帧（带 payload）
  │
  ▼ S3 on_uplink
  ├─ alloc_peer() 首次 → USB → {"type":"device","event":"online","mac":"AA:..","model":"c3-light","name":"living_room",...}
  └─ HELLO 带 payload  → USB → {"type":"state","mac":"AA:..","hop":1,"via":"7C:..","payload":{...}}
  │
  ▼ Bridge._handle_serial
  ├─ device 行 → _on_device_event
  │     ├─ MQTT ← espnow2mqtt/living_room/availability = "online"   (retained)
  │     └─ MQTT ← espnow2mqtt/bridge/devices = [{...}]              (retained)
  └─ state 行  → _on_state
        ├─ merged = {} + payload + 注入 hop/via/caps
        ├─ MQTT ← espnow2mqtt/living_room/state = {...}             (retained)
        └─ MQTT ← espnow2mqtt/living_room/<key> × N                 (不 retained)
  │
  ▼ HA 集成
  ├─ bridge/devices → hub._on_devices
  │     ├─ devices["AA:.."] = EspNowDevice(name="living_room", model="c3-light", online=True, rssi=-58, hop=1)
  │     └─ SIGNAL_DEVICE_UPDATED("AA:..")
  │           └─ 七个平台 _discover：caps 还是空的 → 只有 sensor 会建
  │                 hop / node_role 两个诊断实体（+ rssi，因为 dev.rssi 不是 None）
  ├─ living_room/availability → hub._on_availability → online = True
  └─ living_room/state → hub._on_device_state
        ├─ 找到 mac = "AA:.."（设备列表先到，所以不会建 slug: 占位）
        ├─ caps = ["light"]（payload 里有显式 caps）
        ├─ brightness 在 payload 里 → 已经有 light，不重复加
        ├─ merged / 归一化 / dev.online = True
        └─ SIGNAL_DEVICE_UPDATED("AA:..")
              ├─ light._discover：caps 里有 light → ★ 建 EspNowLight
              ├─ switch._discover：caps 里没有 switch → 跳过
              ├─ sensor._discover：hop/node_role/rssi 已建 → 跳过
              └─ 已有实体的 _handle_update → async_write_ha_state()

结果：HA 里出现设备 "Living Room"，带
  light.living_room_light
  sensor.living_room_mesh_hop      (diagnostic)
  sensor.living_room_node_role     (diagnostic)
  sensor.living_room_rssi          (diagnostic)
```

**注意实体是分两批建出来的**：诊断实体在 `bridge/devices` 到达时就建了，
功能实体要等 `<slug>/state` 到达（因为 caps 只从那里来）。
两者通常相隔几毫秒，用户感知不到。

---

## 9. 完整时序：一次开灯

```
用户：在 HA 里把灯的亮度拉到 50%
  │
  ▼ HA 调用 light.turn_on(entity_id=light.living_room_light, brightness=128)
EspNowLight.async_turn_on(brightness=128)
  │  payload = {"switch": "ON"}
  │  level = max(1, min(254, round(128 * 254 / 255))) = 128
  │  payload["brightness"] = 128
  ▼ hub.async_publish_set(dev, {"switch":"ON","brightness":128})
MQTT ← espnow2mqtt/living_room/set = {"switch":"ON","brightness":128}
  │
  ▼ Bridge._on_mqtt_message
  │  slug = "living_room" → _find_by_slug → dev.mac
  │  cid = self.cmd_id++ （非零 ⇒ 启用 ACK/重传）
USB  ← {"type":"cmd","mac":"AA:..","id":7,"payload":{"switch":"ON","brightness":128}}
  │
  ▼ S3 handle_host_line → en2m_send_downlink(mac, 7, payload, len)
空口 ← CMD 帧（0 / 400 / 800 / 1200 ms 重传直到 ACK）
  │
  ▼ C3 设备
  │  解析扁平 payload → en2m_attribute_write(OnOff.ON_OFF, true)
  │                   → en2m_attribute_write(LevelControl.CURRENT_LEVEL, 128)
  │  写回调驱动 PWM，返回 ESP_OK → 属性提交 → attribute_changed
空口 → ACK 帧（cmd_id=7）
空口 → STATE 帧（新状态）
  │
  ▼ S3 on_uplink
USB  → {"type":"ack","mac":"AA:..","id":7,"ok":true,...}
USB  → {"type":"state","mac":"AA:..","payload":{"switch":"ON","brightness":128,...}}
  │
  ▼ Bridge
  ├─ ack → LOG.debug（不进 MQTT）
  └─ state → merged → MQTT ← espnow2mqtt/living_room/state = {...}
  │
  ▼ HA 集成 hub._on_device_state
  │  dev.state["brightness"] = 128
  └─ SIGNAL_DEVICE_UPDATED → EspNowLight._handle_update → async_write_ha_state()
  │
  ▼ EspNowLight.brightness 被重新读取
     raw = 128 → round(128 * 255 / 254) = 128 → HA 显示 128
```

**整个往返通常几百毫秒。** UI 上的表现是滑条拉到位、稍微停顿一下、
然后状态确认（HA 前端有乐观更新，所以视觉上很流畅）。

注意亮度经过了**两次换算**：HA 0–255 → 固件 0–254 → HA 0–255。
`round(round(128*254/255)*255/254) = 128`，在大部分值上是无损的，
但个别值会差 1（见 [entities.md](entities.md#31-亮度0254--0255)）。

**如果命令失败**（设备断电），链路会在 S3 那里断掉：
`{"ok":false,"error":"timeout"}` → Bridge 打一条 `WARNING` →
**MQTT 上什么都不发** → HA 里实体状态不变。

所以 **HA 侧感知命令失败的唯一方式是"状态没变"**。
见 [usage.md §7](usage.md#7-命令是单向的)。

---

## 10. HA 重启后会发生什么

`hub.devices` 是纯内存的，**没有任何持久化**。
重启后全靠 MQTT 上的 retained 消息重建。

| 主题 | retained？ | 重启后 |
|---|:-:|---|
| `bridge/state` | ✓ | 立刻恢复 → `bridge_online` |
| `bridge/devices` | ✓ | 立刻恢复 → 全部设备的 name/model/online/rssi/hop/via/role |
| `<slug>/state` | ✓ | 立刻恢复 → caps 和业务状态 |
| `<slug>/availability` | ✓ | 立刻恢复 → online |
| `<slug>/<key>`（扁平） | ✗ | **集成不订阅这些，无关** |

所以**重启后几乎是瞬间恢复的**——四个订阅建立后 retained 消息立刻涌入，
平台起来时全部设备已经在表里了。

实体不会重新创建（HA 的实体注册表按 `unique_id` 认人），
所以实体 ID 和历史数据都保留。

### 唯一会"变差"的情况

`dev.state` 清空了，所以**这一轮的 `merged` 只有 retained 消息里的字段**。
如果 Bridge 也刚重启过、它发的 retained `<slug>/state` 是残缺的
（缺 `caps` 之类），那集成拿到的也是残缺的。

表现：某些实体短暂 unknown，几轮上报后补齐。
详见 host 仓库 `docs/bridge.md` 的 "Bridge 重启后第一条状态可能是残缺的"。

### 如果 MQTT broker 也重启了

retained 消息存在 broker 的持久化存储里（Mosquitto 默认
`autosave_interval 1800` 秒写一次 `mosquitto.db`）。
broker 重启可能丢最近 30 分钟的 retained 消息。

那时候集成会**什么设备都没有**，直到：

- Bridge 的下一次 `hello`（30 s）→ `bridge/state` + `bridge/info`
- 下一条 `device` 行（每设备 30 s）→ `bridge/devices`
- 下一条设备上报（30 s）→ `<slug>/state`

所以最多等一分钟就全回来了。

---

## 相关文档

- [architecture.md](architecture.md) — Hub / Entity / Platform 的分层和信号机制
- [entities.md](entities.md) — 每个平台的字段映射和单位换算
- [usage.md](usage.md) — 服务和自动化
- [troubleshooting.md](troubleshooting.md) — 按症状排查
- [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) — 上游主题的权威定义
- [device 仓库 docs/state-flow.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/state-flow.md) — 设备侧的状态机
