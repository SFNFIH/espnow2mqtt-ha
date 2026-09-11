# 集成架构

整个集成 **1786 行 Python，15 个文件**，没有任何第三方依赖
（`manifest.json` 里 `"requirements": []`）。

它的结构是 HA 自定义集成里最经典的那种：**一个 Hub 持有全部状态，
实体是 Hub 状态的无状态视图，dispatcher 信号把两者连起来。**

目录：

1. [三层分工](#1-三层分工)
2. [文件职责](#2-文件职责)
3. [Hub：唯一的状态持有者](#3-hub唯一的状态持有者)
   - [3.4 `bridge/info`：协调器自述](#34-bridgeinfo协调器自述)
4. [`EspNowDevice`：设备模型](#4-espnowdevice设备模型)
5. [Entity 基类与可用性](#5-entity-基类与可用性)
6. [Dispatcher 信号](#6-dispatcher-信号)
7. [平台的动态发现模式](#7-平台的动态发现模式)
8. [Config Entry 生命周期](#8-config-entry-生命周期)
9. [为什么不用 MQTT Discovery](#9-为什么不用-mqtt-discovery)
10. [设备注册表的层级](#10-设备注册表的层级)

---

## 1. 三层分工

```
          MQTT (paho, 由 HA 的 mqtt 集成管)
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ hub.py — EspNowHub                           │  ← 唯一持有状态的地方
│   订阅 6 个主题 → 更新 self.devices          │
│   发 dispatcher 信号                         │
│   提供 async_publish_set / async_permit_join │
└──────────────────────────────────────────────┘
                      │ SIGNAL_DEVICE_UPDATED(entry_id, mac)
                      │ SIGNAL_DEVICE_REMOVED(entry_id, mac)
                      │ SIGNAL_BRIDGE_UPDATED(entry_id)
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ discovery.py │ │ 各平台的 │ │ entity.py    │
│ 共用的发现   │ │ _build() │ │ EspNowEntity │
│ 骨架         │ │ 说要什么 │ │ 刷新/自删    │
└──────────────┘ └──────────┘ └──────────────┘
   sensor / binary_sensor / switch / light / fan / cover / lock / climate / event
```

三条铁律：

| 铁律 | 为什么 |
|---|---|
| **实体不持有状态** | 所有 `@property` 都从 `self._device.state` 现算。没有缓存，没有同步问题 |
| **实体不直接发 MQTT** | 全部走 `self._hub.async_publish_set()`。主题拼接只有一处 |
| **Hub 不知道实体存在** | Hub 只发广播信号，不持有实体引用。加新平台不用改 Hub |

`_attr_should_poll = False`（`entity.py`）——这是个纯推送集成，
HA 永远不会主动调用 `update()`。

---

## 2. 文件职责

| 文件 | 行数 | 职责 |
|---|---:|---|
| `hub.py` | 421 | **核心**。MQTT 订阅、设备表、caps 推断、状态归一化、占位设备合并、发布助手 |
| `entity.py` | 163 | `EspNowEntity` 基类：unique_id、device_info、availability、属性、信号订阅、**过期自删** |
| `sensor.py` | 159 | 6 个测量量 + 3 个诊断量 |
| `binary_sensor.py` | 139 | 5 个二元传感器 + **Bridge 连通性实体** |
| `light.py` | 116 | 亮度/色温，含 0–254↔0–255 和 mired↔Kelvin 换算 |
| `climate.py` | 112 | 温控器，5 个 HVAC 模式 |
| `__init__.py` | 104 | Config entry 装卸、平台转发、`permit_join` 服务、设备移除清理 |
| `config_flow.py` | 103 | UI 配置流 + 选项流（只有一个选项：base topic） |
| `event.py` | 100 | 按钮事件（`button` cap） |
| `cover.py` | 96 | 窗帘，**含 HA 开度% ↔ 固件关闭% 的反转** |
| `fan.py` | 95 | 百分比 + 7 个 preset mode |
| `discovery.py` | 58 | 所有平台共用的动态发现骨架（[§7](#7-平台的动态发现模式)） |
| `lock.py` | 49 | 门锁 |
| `switch.py` | 48 | 开关（**排除已被识别为灯的设备**） |
| `const.py` | 23 | 域名、默认主题、主题后缀常量、命令失败事件名 |

`const.py` 里的 `ATTR_MAC` / `ATTR_CAPS` / `ATTR_HOP` / `ATTR_VIA` /
`ATTR_NODE_ROLE` 是 `EspNowEntity.extra_state_attributes` 的键名，
所以每个设备实体都带着自己的 MAC、能力列表和 mesh 拓扑，
模板里可以直接取（[usage.md §5](usage.md#5-在模板里取值)）。

> 0.3.x 里这五个常量没有任何地方引用，拓扑信息只能从 `sensor.*_mesh_hop`
> 这类诊断实体绕着拿。

---

## 3. Hub：唯一的状态持有者

```python
class EspNowHub:
    def __init__(self, hass, entry, base_topic):
        self.base = base_topic.rstrip("/")
        self.devices: dict[str, EspNowDevice] = {}
        self.bridge_online = False
        self.bridge_info: dict[str, Any] = {}
        self._unsubs: list[Callable[[], None]] = []
```

一个 config entry 一个 Hub，存在 `hass.data[DOMAIN][entry.entry_id]`。
**可以有多个**：一个协调器一个条目，各自一套主题前缀
（[§8.5](#85-一个协调器一个-entry)）。

`self.discovered` 是所有平台共用的"已创建过的 unique_id"集合。
它放在 Hub 上而不是各平台内部，是为了让一个自删掉的实体
之后还能被重新创建（[§7](#7-平台的动态发现模式)）。

### 3.1 六个 MQTT 订阅

`async_start()` 里，全部 **QoS 0**：

| 订阅的主题 | 回调 | 干什么 |
|---|---|---|
| `<base>/bridge/state` | `_on_bridge_state` | 设 `self.bridge_online`，发 `SIGNAL_BRIDGE_UPDATED`，并扇出给所有设备 |
| `<base>/bridge/info` | `_on_bridge_info` | 存协调器自述（信道、固件、MAC），见 [§3.4](#34-bridgeinfo协调器自述) |
| `<base>/bridge/devices` | `_on_devices` | 遍历数组，更新 name/model/online/node_role/via/hop/rssi，合并占位设备 |
| `<base>/+/state` | `_on_device_state` | **最重要的一个**：合并状态、推断 caps、归一化 |
| `<base>/+/availability` | `_on_availability` | 按 slug 找设备，设 `online` |
| `<base>/+/command_result` | `_on_command_result` | 命令的成败，失败时抛 HA 事件，见 [usage.md §7](usage.md#7-命令的成败反馈) |

`_unsubs` 存所有退订函数，`async_stop()` 里 pop 光。

### 3.2 通配符订阅会撞到 bridge

`<base>/+/state` 这个通配符**也会匹配 `<base>/bridge/state`**，
所以 `_on_device_state` 开头有一道显式过滤：

```python
slug = parts[-2]
if slug == "bridge":
    return
```

`<base>/+/availability` 不需要这道过滤，因为 Bridge 没有
`bridge/availability` 这个主题。

### 3.3 payload 的 bytes/str 兼容

每个回调开头都有：

```python
raw = msg.payload
if isinstance(raw, bytes):
    raw = raw.decode("utf-8", errors="ignore")
```

HA 的 `mqtt.ReceiveMessage.payload` 在不同版本/不同 encoding 配置下
可能是 `str` 也可能是 `bytes`，这是防御性写法。`errors="ignore"`
保证畸形字节不会抛异常。

### 3.4 `bridge/info`：协调器自述

`<base>/bridge/info` 是 retained 的，内容就是协调器上电时那条 `hello` 行
被 Bridge 原样转发的结果：

```json
{"type":"hello","version":2,"role":"coordinator",
 "mac":"AA:BB:CC:DD:EE:FF","fw":"0.4.0-idf",
 "channel":1,"mesh":true,"stack":"esp-idf"}
```

Hub 把它存进 `self.bridge_info`，然后有两个去处：

| 去处 | 内容 |
|---|---|
| `binary_sensor.esp_now_coordinator_bridge` 的属性 | `mac`、`fw`、`channel`、`version`、`role`、`stack`，再加上 `base_topic` 和当前设备数 |
| 协调器那个设备条目的 `sw_version` | 就是 `fw` |

> **`sw_version` 要专门写一次。** `device_info` 只在实体**第一次**被加入时读一遍，
> 而 Bridge 实体是在 `async_setup_entry` 里直接建的，那时
> `bridge/info` 还没到。所以 `_on_bridge` 回调里会调
> `async_sync_device_registry()`（`entity.py`），把迟到的固件版本
> 补写进设备注册表。设备实体的 `model` 同理。

> 0.3.x 里 `TOPIC_BRIDGE_INFO` 这个常量存在、`self.bridge_info` 这个字段也存在，
> **但从来没有订阅过这个主题**，所以 `bridge_info` 恒为空字典，
> 协调器的信道和固件版本在 HA 里根本看不到。

---

## 4. `EspNowDevice`：设备模型

```python
@dataclass
class EspNowDevice:
    mac: str
    name: str = ""
    model: str = ""
    online: bool = False
    caps: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)
    hop: int | None = None
    via: str = ""
    node_role: str = ""
    rssi: int | None = None

    @property
    def slug(self) -> str:
        return slug_from_name_or_mac(self.name, self.mac)
```

| 字段 | 哪个订阅会写 | 用在哪 |
|---|---|---|
| `mac` | 建对象时 | `unique_id` 前缀、设备注册表 `identifiers` |
| `name` | `bridge/devices`；`+/state` 时兜底用 slug | 设备显示名 |
| `model` | `bridge/devices` | 设备注册表的 `model` |
| `online` | 三个订阅都会写 | **实体可用性** |
| `caps` | 只有 `+/state` | **决定创建哪些实体**（[entities.md](entities.md)） |
| `state` | 只有 `+/state` | 所有实体的取值来源 |
| `hop` / `via` | `bridge/devices` 和 `+/state` | 诊断 sensor |
| `node_role` | `bridge/devices` 和 `+/state` | 诊断 sensor |
| `rssi` | **只有 `bridge/devices`** | 诊断 sensor |

注意 **`rssi` 只从 `bridge/devices` 来**——设备的 `<slug>/state` payload 里
没有 RSSI（那是协调器观测到的，Bridge 只把它放进设备列表）。
所以 RSSI 实体的刷新频率取决于 `bridge/devices` 的重写频率
（Bridge 每收到一条 `device` 行就重写一次，即每设备 30 s）。

`slug` 是**算出来的属性，不是存的字段**：

```python
def slug_from_name_or_mac(name: str, mac: str) -> str:
    if name:
        return name.replace(" ", "_").lower()
    return mac.replace(":", "").lower()
```

**这和 Bridge 的 `_slug()` 是逐字相同的算法**——必须相同，否则
集成发到 `<slug>/set` 的命令 Bridge 找不到设备。
两边各写了一份（没有共享代码），改一边必须改另一边。

---

## 5. Entity 基类与可用性

```python
class EspNowEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub, device, key):
        self._hub = hub
        self._device = device
        self._key = key
        self._attr_unique_id = f"{device.mac}_{key}"
```

| 约定 | 值 | 含义 |
|---|---|---|
| `unique_id` | `f"{mac}_{key}"` | 例：`AA:BB:CC:DD:EE:FF_temperature` |
| `has_entity_name` | `True` | 实体名会显示成"设备名 + 实体名"，所以各平台的 `_attr_name` 都是短名（`"Switch"`、`"Temperature"`） |
| `should_poll` | `False` | 纯推送 |

### 5.1 可用性是**两个条件的与**

```python
@property
def available(self) -> bool:
    return self._hub.bridge_online and self._device.online
```

这是刻意的：Bridge 挂掉时，设备的 `<slug>/availability` 还是 retained 的
`online`（Bridge 挂了没人去改它），**只看设备级可用性会误判**。
把 hub 可用性串进来，Bridge 一挂所有实体立刻变灰。

| `bridge_online` | `device.online` | 实体 |
|:-:|:-:|---|
| ✓ | ✓ | 可用 |
| ✓ | ✗ | 不可用（设备离线） |
| ✗ | 任意 | **不可用**（Bridge 挂了） |

`bridge_online` 初值是 `False`，只有收到 `<base>/bridge/state` 才会变。
因为那是 retained 消息，订阅时立刻就会收到——**除非 base topic 配错了**，
那种情况下所有实体永远是灰的。这是"实体全灰"的第一排查点。

### 5.2 `EspNowBridgeBinary` 是个例外

`binary_sensor.py` 里的 Bridge 连通性实体**不继承 `EspNowEntity`**，
它直接继承 `BinarySensorEntity`：

```python
class EspNowBridgeBinary(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Bridge"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False
```

所以它**没有 `available` 属性覆盖，永远可用**——这是对的：
一个报告"Bridge 是否在线"的实体自己不能因为 Bridge 离线而变灰，
否则你就分不清"Bridge 离线"和"这个实体坏了"。

它的 `unique_id` 是 `f"{hub.entry.entry_id}_bridge"`，
挂在独立的设备 `(DOMAIN, "bridge")` 上。

### 5.3 `_handle_update`：过滤、刷新、自删

```python
@callback
def _handle_update(self, entry_id: str, mac: str) -> None:
    if entry_id != self._hub.entry.entry_id or mac != self._device.mac:
        return
    self._device = self._hub.devices.get(mac, self._device)
    if self._is_stale():
        self._schedule_purge()
        return
    async_sync_device_registry(self.hass, self._device.mac, model=self._device.model)
    self.async_write_ha_state()
```

第一行是**最重要的一行**：dispatcher 是广播的，每条 MQTT 消息都会通知
**所有**实体，这道过滤避免了 N 个设备时的 N² 次状态写入。

`_is_stale()` 判断这个实体赖以存在的那个 cap 还在不在：

```python
def _is_stale(self) -> bool:
    # caps 为空表示"还不知道"，不是"什么都不支持"，绝不能据此删实体
    return bool(
        self._requires_cap
        and self._device.caps
        and self._requires_cap not in self._device.caps
    )
```

每个平台的实体类把 `_requires_cap` 设成自己对应的 cap
（Switch 是 `switch`、Cover 是 `cover`……）；诊断实体
（hop / rssi / node_role）留空，因为它们对每个 mesh 节点都成立，
不依赖任何能力。详见 [§7](#7-平台的动态发现模式) 和
[state-flow.md §6](state-flow.md#6-实体能增也能减)。

> 0.3.x 里这个方法的中间分支条件写反了——写的是
> `if mac != self._device.mac and mac in self._hub.devices:` 才刷新指针，
> 也就是**只在信号不是发给自己的时候**才去刷新自己的指针。
> 因为 Hub 从不替换对象，这个分支实际等价于无操作，所以没造成可见故障，
> 但它表达的意思和它做的事是两回事。

---

## 6. Dispatcher 信号

```python
SIGNAL_DEVICE_UPDATED = f"{DOMAIN}_device_updated"   # "espnow2mqtt_device_updated"
SIGNAL_DEVICE_REMOVED = f"{DOMAIN}_device_removed"   # "espnow2mqtt_device_removed"
SIGNAL_BRIDGE_UPDATED = f"{DOMAIN}_bridge_updated"   # "espnow2mqtt_bridge_updated"
```

| 信号 | 参数 | 谁发 | 谁收 |
|---|---|---|---|
| `SIGNAL_DEVICE_UPDATED` | `(entry_id, mac)` | `_on_devices`（每个数组元素一次）、`_on_availability`、`_on_device_state`、`_on_bridge_state`（扇出给所有设备） | **每个平台的 `_discover()`**（建实体）+ **每个 `EspNowEntity`**（刷状态或自删） |
| `SIGNAL_DEVICE_REMOVED` | `(entry_id, mac)` | `_absorb_placeholder` | `EspNowEntity`（自删）+ `__init__.py` 的 `_device_removed`（删设备条目、清 `hub.discovered`） |
| `SIGNAL_BRIDGE_UPDATED` | `(entry_id,)` | `_on_bridge_state`、`_on_bridge_info` | 只有 `EspNowBridgeBinary` |

`SIGNAL_BRIDGE_UPDATED` 仍然只被 Bridge 实体订阅，但这不再是问题：
`_on_bridge_state` 在发完这个信号之后，会**再对每个已知 MAC 发一遍
`SIGNAL_DEVICE_UPDATED`**，所以 Bridge 一掉线，所有设备实体立刻重算
`available` 并变灰。

```python
@callback
def _on_bridge_state(self, msg):
    self.bridge_online = self._text(msg.payload).strip().lower() == "online"
    async_dispatcher_send(self.hass, SIGNAL_BRIDGE_UPDATED, self.entry.entry_id)
    for mac in list(self.devices):
        async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac)
```

> 0.3.x 里没有这个扇出。因为 Bridge 挂了就不会再有状态上报，
> 设备实体拿不到任何 `SIGNAL_DEVICE_UPDATED`，于是**一直停在"可用"状态
> 直到 HA 重启**——只有 `binary_sensor.*_bridge` 会变成 off。

`async_dispatcher_send` 是同步派发（在 HA 的事件循环上直接调用所有回调），
所以一条 MQTT 消息的处理是原子的，没有并发问题。这也是为什么
Hub 里**一把锁都没有**——不像 Bridge 那边有多线程问题
（见 host 仓库 `docs/bridge.md` 的并发弱点一节）。

---

## 7. 平台的动态发现模式

七个平台文件用的是**完全相同的骨架**：

```python
async def async_setup_entry(hass, entry, async_add_entities):
    hub: EspNowHub = hass.data[DOMAIN][entry.entry_id]

    def _build(hub, device) -> list[Entity]:
        if "<cap>" not in device.caps:
            return []
        return [EspNow<X>(hub, device)]

    async_setup_device_discovery(hass, entry, hub, async_add_entities, _build)
```

每个平台只剩一个 `_build()`，说清"给这个设备，我要哪些实体"。
其余的全在 `discovery.py` 里：

```python
@callback
def async_setup_device_discovery(hass, entry, hub, async_add_entities, build):
    @callback
    def _discover(entry_id: str, mac: str) -> None:
        if entry_id != entry.entry_id:
            return
        device = hub.devices.get(mac)
        if device is None:
            return
        fresh = [
            entity for entity in build(hub, device)
            if entity.unique_id and entity.unique_id not in hub.discovered
        ]
        if not fresh:
            return
        hub.discovered.update(entity.unique_id for entity in fresh)
        async_add_entities(fresh)

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)
```

四个要点：

| 要点 | 说明 |
|---|---|
| **`hub.discovered` 在 Hub 上，不在各平台闭包里** | 这是关键。实体自删的时候会 `hub.discovered.discard(uid)`，于是同一个 uid 之后**还能再被创建**。0.3.x 里这个集合是每个平台的局部 `known`，实体删掉了也没法通知它，所以 cap 回来了实体也回不来 |
| **`build()` 必须无副作用** | 它在每次更新时都被调用，返回的实体如果 uid 已存在就直接丢掉，根本不会进 hass。所以实体的 `__init__` 里不能做有副作用的事——这也是灯的色彩模式必须做成动态属性而不能在 `__init__` 里定死的原因之一 |
| **先注册信号，再扫一遍现有设备** | 顺序很重要：如果先扫再注册，扫描和注册之间到达的消息会丢 |
| **`entry.async_on_unload`** | 卸载 entry 时自动退订，不会泄漏回调 |

`_discover` 会在**每一条 MQTT 消息**上被调用（八个平台各一次），
大部分时候 `build()` 立刻返回空表或者返回的 uid 全都已存在。
这个开销可以忽略。

因为 uid 的形式是 `f"{mac}_{key}"` 而各平台的 `key` 互不相同，
共用一个集合不会撞车。

条件的差异见 [entities.md](entities.md#1-caps--平台映射)。
只有两个平台不是简单的 `"<cap>" in caps`：

- `switch.py`：`"switch" in caps and "light" not in caps`
  （被识别成灯的设备不再出 Switch 实体）
- `sensor.py`：诊断量 `hop` / `node_role` 无条件要，`rssi` 在有值时要，
  测量量则要求它真的在 caps 里

---

## 8. Config Entry 生命周期

### 8.1 装载

```python
async def async_setup_entry(hass, entry) -> bool:
    base = entry.options.get(
        CONF_BASE_TOPIC, entry.data.get(CONF_BASE_TOPIC, DEFAULT_BASE_TOPIC)
    )
    hub = EspNowHub(hass, entry, base)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = hub
    await hub.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    ...
```

**顺序很关键：`hub.async_start()` 在 `async_forward_entry_setups()` 之前。**

这意味着订阅先建立，retained 消息可能在平台还没起来时就到了。
没问题——那些消息会填进 `hub.devices`，平台起来后的"扫一遍现有设备"
就能看到它们。反过来（先起平台再订阅）会漏掉第一批 retained 消息。

`base` 的取值优先级：**options → data → 默认值**。
options 优先是为了让选项流能覆盖初始配置。

### 8.2 服务注册

```python
if not hass.services.has_service(DOMAIN, SERVICE_PERMIT_JOIN):
    hass.services.async_register(
        DOMAIN, SERVICE_PERMIT_JOIN, _permit_join,
        schema=vol.Schema({
            vol.Optional(ATTR_DURATION, default=60): vol.All(vol.Coerce(int), vol.Range(1, 300))
        }),
    )
```

`permit_join` 是**域级服务**（不是实体服务），所以只注册一次
（`has_service` 检查）。它会对**所有** Hub 发一遍：

```python
async def _permit_join(call: ServiceCall) -> None:
    duration = int(call.data.get(ATTR_DURATION, 60))
    for h in hass.data[DOMAIN].values():
        if isinstance(h, EspNowHub):
            await h.async_permit_join(duration)
```

配了多个协调器时，这个循环会**同时打开所有协调器的配对窗口**。
想只开一个的话直接往那个前缀发 MQTT：
`mosquitto_pub -t espnow2mqtt_upstairs/bridge/request/permit_join -m 60`。

### 8.3 选项变更 → 重载

```python
entry.async_on_unload(entry.add_update_listener(_async_update_listener))

async def _async_update_listener(hass, entry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
```

改了 base topic 就**整个 entry 重载**：退订旧主题、丢掉整个设备表、
用新前缀重新订阅。这是最简单也最正确的做法——base topic 变了，
旧设备表里的一切都不再相关。

**代价**：所有实体会短暂变成不可用，然后随着新的 retained 消息重新填充。
如果新前缀下没有 Bridge，实体会永远不可用（但不会被删除，
因为 `unique_id` 还在 HA 的注册表里）。

### 8.4 卸载

```python
async def async_unload_entry(hass, entry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_stop()
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_PERMIT_JOIN)
            hass.data.pop(DOMAIN, None)
    return unload_ok
```

先卸平台（实体退订 dispatcher），再退 MQTT 订阅。
最后一个 Hub 走的时候才注销服务并清掉 `hass.data[DOMAIN]`。

### 8.5 一个协调器一个 entry

`config_flow.py`：

```python
async def async_step_user(self, user_input=None):
    if not _mqtt_is_ready(self.hass):
        return self.async_abort(reason="mqtt_not_ready")
    if user_input is not None:
        base = _clean(user_input.get(CONF_BASE_TOPIC))
        await self.async_set_unique_id(f"{DOMAIN}:{base}")
        self._abort_if_unique_id_configured()
        ...
```

两道 abort：

| reason | 何时 | 提示文本（`strings.json`） |
|---|---|---|
| `already_configured` | **这个主题前缀上**已经有一个 entry | "A coordinator is already configured on this base topic" |
| `mqtt_not_ready` | HA 里还没配 MQTT 集成 | "MQTT integration is not set up. Add MQTT first." |

`unique_id` 是 `f"{DOMAIN}:{base}"`，所以**限制的是主题前缀而不是条目数量**。
两个协调器各用自己的前缀就能同时接进来（[usage.md §11](usage.md#11-多个协调器)）。
选项流改前缀时也会查一遍别的条目有没有占用，占了就在表单上报错而不是静默重复。

`_mqtt_is_ready()` 查的是**有没有一个已加载的 MQTT config entry**：

```python
def _mqtt_is_ready(hass: HomeAssistant) -> bool:
    return any(
        entry.state is ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries(mqtt.DOMAIN)
    )
```

> 0.3.x 查的是 `mqtt.DOMAIN not in self.hass.config.components`，
> 这个判断**永远不成立**：`manifest.json` 的 `dependencies` 里写了 `mqtt`，
> HA 一开始这个流程就会把 `mqtt` 作为依赖加载上，于是 `components` 里必然有它。
> 也就是说那个 abort 分支不可达，没配 broker 的人会一路走到表单，
> 建出一个永远收不到消息的条目。

配置项只有一个：**base topic**。默认 `espnow2mqtt`，
输入时会 `.strip().strip("/")`，空串回落到默认值。

---

## 9. 为什么不用 MQTT Discovery

Bridge 自己带一个 `--ha-discovery` 开关（默认关）。这个集成是它的替代品。

| | 内置 MQTT Discovery | 本集成 |
|---|---|---|
| 支持的能力 | **7 种**：switch / temperature / humidity / contact / power / energy / button | **全部**：+ light / fan / cover / lock / climate / occupancy / motion / smoke / CO / pressure / illuminance |
| 灯的亮度和色温 | ✗ | ✓（含单位换算） |
| 窗帘 / 门锁 / 风扇 / 温控器 | ✗ | ✓ |
| 配对入口 | 只能手工发 MQTT | `espnow2mqtt.permit_join` 服务 |
| 单位换算 | 靠 `value_template` | Python 里做，可以有条件逻辑 |
| Bridge 可用性联动 | 每个实体独立的 `availability_topic` | `bridge_online and device.online` |

> **不要两个都开。** 会出现两套实体
> （`sensor.x_temperature` 和 `sensor.x_temperature_2`），自动化会引用错的那个。
>
> Bridge 的 `--ha-discovery` 默认就是关的，保持默认即可。
> 如果你之前开过，关掉之后**已经发出的 retained config 主题不会自动消失**，
> 得手工清（见 host 仓库 `docs/mqtt.md` 的"清理 discovery"）。

---

## 10. 设备注册表的层级

集成会在 HA 里建出两级设备：

```
ESP-NOW Coordinator                      identifiers={(DOMAIN, "bridge")}
  └─ binary_sensor.*_bridge  (connectivity)
  │
  ├─ Living Room                         identifiers={(DOMAIN, "AA:BB:CC:DD:EE:FF")}
  │    ├─ light.living_room_light        via_device=(DOMAIN, "bridge")
  │    ├─ sensor.living_room_mesh_hop    (diagnostic)
  │    └─ sensor.living_room_node_role   (diagnostic)
  │
  └─ Bedroom Sensor                      identifiers={(DOMAIN, "AA:BB:CC:DD:EE:01")}
       ├─ sensor.bedroom_sensor_temperature
       ├─ sensor.bedroom_sensor_humidity
       └─ ...
```

`entity.py` 的 `device_info`：

```python
return DeviceInfo(
    identifiers={(DOMAIN, dev.mac)},
    name=dev.name or dev.slug,
    manufacturer="espnow2mqtt",
    model=dev.model or "ESP-NOW node",
    via_device=(DOMAIN, "bridge"),
    connections=connections or None,
)
```

| 字段 | 值 | 备注 |
|---|---|---|
| `identifiers` | `(DOMAIN, mac)` | 设备的稳定身份。**MAC 变了就是新设备** |
| `name` | `dev.name or dev.slug` | 设备没报 name 时用紧凑 MAC |
| `model` | `dev.model or "ESP-NOW node"` | `model` 来自 `bridge/devices` |
| `via_device` | `(DOMAIN, "bridge")` | **让 HA 画出"通过协调器连接"的层级** |
| `connections` | `{("mac", mac.lower())}` | 只在 MAC 看起来像真 MAC 时加 |

`connections` 的条件：

```python
if ":" in dev.mac and not dev.mac.startswith("slug:"):
    connections.add(("mac", dev.mac.lower()))
```

`slug:` 前缀的判断是为了排除占位设备（见
[state-flow.md §3.3](state-flow.md#33-slug-占位设备)）。
给占位设备加 `("mac", "slug:relay1")` 这种连接会污染 HA 的设备注册表，
甚至可能和别的集成的设备意外合并。占位设备被合并掉时，
`__init__.py` 的 `_device_removed` 会把它的设备条目也从注册表里摘掉，
所以那一栏不会留下一个空壳设备。

Bridge 那个设备是由 `EspNowBridgeBinary` 单独声明的：

```python
info = self._hub.bridge_info
DeviceInfo(
    identifiers={(DOMAIN, "bridge")},
    name="ESP-NOW Coordinator",
    manufacturer="espnow2mqtt",
    model="USB Coordinator Bridge",
    sw_version=str(info["fw"]) if info.get("fw") else None,
    connections={("mac", str(info["mac"]).lower())} if ... else None,
)
```

`sw_version` 和 `connections` 都来自 `bridge/info`
（[§3.4](#34-bridgeinfo协调器自述)）。因为这个实体在 `bridge/info` 到达
之前就建好了，`device_info` 那一遍读到的是空的，所以 `_on_bridge` 回调里
还会再调一次 `async_sync_device_registry()` 把固件版本补写进去。

---

## 相关文档

- [state-flow.md](state-flow.md) — 一条 MQTT 消息的完整旅程，实体怎么被创建
- [entities.md](entities.md) — caps → 平台映射，每个实体的字段和单位换算
- [usage.md](usage.md) — 服务、自动化、模板
- [troubleshooting.md](troubleshooting.md) — 按症状排查
- [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) — 本集成读写的每个主题的权威定义
- [host 仓库 docs/bridge.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/bridge.md) — 上游的状态合并逻辑
