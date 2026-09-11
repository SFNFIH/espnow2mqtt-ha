# 集成架构

整个集成 **1447 行 Python，13 个文件**，没有任何第三方依赖
（`manifest.json` 里 `"requirements": []`）。

它的结构是 HA 自定义集成里最经典的那种：**一个 Hub 持有全部状态，
实体是 Hub 状态的无状态视图，dispatcher 信号把两者连起来。**

目录：

1. [三层分工](#1-三层分工)
2. [文件职责](#2-文件职责)
3. [Hub：唯一的状态持有者](#3-hub唯一的状态持有者)
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
│   订阅 4 个主题 → 更新 self.devices          │
│   发 dispatcher 信号                         │
│   提供 async_publish_set / async_permit_join │
└──────────────────────────────────────────────┘
                      │ SIGNAL_DEVICE_UPDATED(entry_id, mac)
                      │ SIGNAL_BRIDGE_UPDATED(entry_id)
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
┌──────────────┐ ┌──────────┐ ┌──────────────┐
│ 平台的       │ │ 平台的   │ │ entity.py    │
│ _discover()  │ │ _discover│ │ EspNowEntity │
│ 创建实体     │ │ ...      │ │ 刷新状态     │
└──────────────┘ └──────────┘ └──────────────┘
   sensor / binary_sensor / switch / light / fan / cover / lock / climate
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
| `hub.py` | 294 | **核心**。MQTT 订阅、设备表、caps 推断、状态归一化、发布助手 |
| `sensor.py` | 173 | 6 个测量量 + 3 个诊断量 |
| `light.py` | 111 | 亮度/色温，含 0–254↔0–255 和 mired↔Kelvin 换算 |
| `fan.py` | 106 | 百分比 + 7 个 preset mode |
| `binary_sensor.py` | 117 | 5 个二元传感器 + **Bridge 连通性实体** |
| `climate.py` | 100 | 温控器，5 个 HVAC 模式 |
| `cover.py` | 89 | 窗帘，**含 HA 开度% ↔ 固件关闭% 的反转** |
| `__init__.py` | 76 | Config entry 装卸、平台转发、`permit_join` 服务 |
| `config_flow.py` | 69 | UI 配置流 + 选项流（只有一个选项：base topic） |
| `entity.py` | 61 | `EspNowEntity` 基类：unique_id、device_info、availability、信号订阅 |
| `lock.py` | 58 | 门锁 |
| `switch.py` | 57 | 开关（**排除已被识别为灯的设备**） |
| `const.py` | 17 | 域名、默认主题、主题后缀常量 |

`const.py` 里的 `ATTR_MAC` / `ATTR_CAPS` / `ATTR_HOP` / `ATTR_VIA` /
`ATTR_NODE_ROLE` 五个常量**目前没有任何地方引用**——代码里都是直接用字面量
字符串。留着无害，但别以为改了它们会有效果。

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
由于 config flow 限制了**只能有一个 entry**（[§8](#8-config-entry-生命周期)），
实际上永远只有一个 Hub。

### 3.1 四个 MQTT 订阅

`async_start()` 里，全部 **QoS 0**：

| 订阅的主题 | 回调 | 干什么 |
|---|---|---|
| `<base>/bridge/state` | `_on_bridge_state` | 设 `self.bridge_online`，发 `SIGNAL_BRIDGE_UPDATED` |
| `<base>/bridge/devices` | `_on_devices` | 遍历数组，更新 name/model/online/node_role/via/hop/rssi |
| `<base>/+/state` | `_on_device_state` | **最重要的一个**：合并状态、推断 caps、归一化 |
| `<base>/+/availability` | `_on_availability` | 按 slug 找设备，设 `online` |

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

### 3.4 没有订阅 `bridge/info`

`const.py` 里定义了 `TOPIC_BRIDGE_INFO = "bridge/info"`，
`hub.py` 里也有 `self.bridge_info: dict[str, Any] = {}`。

> **但集成从来没有订阅这个主题，`bridge_info` 永远是空字典。**
>
> 后果：集成**拿不到协调器的 ESP-NOW 信道、固件版本、MAC**。
> 这些信息只存在于 MQTT 上（`<base>/bridge/info`，retained），
> 要看只能自己订：
>
> ```bash
> mosquitto_sub -t espnow2mqtt/bridge/info -C 1 | python3 -m json.tool
> ```
>
> 补上这个功能很简单（在 `async_start()` 里加第五个订阅，
> 回调里 `self.bridge_info = json.loads(raw)`），然后就能给
> Bridge 那个设备加上 `sw_version` 和信道诊断实体。
> 当前版本没做。

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

### 5.3 `_handle_update` 里的指针刷新

```python
def _handle_update(self, entry_id: str, mac: str) -> None:
    if entry_id != self._hub.entry.entry_id:
        return
    if mac != self._device.mac and mac in self._hub.devices:
        # 如果 hub 换了对象，刷新指针
        self._device = self._hub.devices.get(self._device.mac, self._device)
    if mac == self._device.mac:
        self.async_write_ha_state()
```

中间那个分支的意图是"Hub 可能用新对象替换了 `devices[mac]`，实体要重新取指针"。
实际上 Hub 从不替换对象（`_on_devices` 里 `dev = self.devices.get(mac) or EspNowDevice(mac=mac)`
是**复用**已有对象的），所以这个分支等价于无操作。留着无害。

真正起作用的是最后两行：**只有信号里的 MAC 是自己的，才刷新 HA 状态。**
因为 dispatcher 是广播的，每条 MQTT 消息都会通知**所有**实体，
这道过滤避免了 N 个设备时的 N² 次状态写入。

---

## 6. Dispatcher 信号

```python
SIGNAL_DEVICE_UPDATED = f"{DOMAIN}_device_updated"   # "espnow2mqtt_device_updated"
SIGNAL_BRIDGE_UPDATED = f"{DOMAIN}_bridge_updated"   # "espnow2mqtt_bridge_updated"
```

| 信号 | 参数 | 谁发 | 谁收 |
|---|---|---|---|
| `SIGNAL_DEVICE_UPDATED` | `(entry_id, mac)` | `_on_devices`（每个数组元素一次）、`_on_availability`、`_on_device_state` | **每个平台的 `_discover()`**（建实体）+ **每个 `EspNowEntity`**（刷状态） |
| `SIGNAL_BRIDGE_UPDATED` | `(entry_id,)` | `_on_bridge_state` | 只有 `EspNowBridgeBinary` |

注意 `SIGNAL_BRIDGE_UPDATED` **只被 Bridge 实体订阅**。
所以 `bridge_online` 变化时，普通设备实体的 `available` 虽然逻辑上变了，
但**不会立刻刷新** ——要等下一条 `SIGNAL_DEVICE_UPDATED`
（也就是下一次状态上报，最多 30 秒）才会重算。

> **实际表现**：Bridge 挂掉后，HA 里的设备实体不会立刻变灰，
> 而是等 Bridge 的 LWT 生效 + 下一次…… 但 Bridge 挂了就不会再有
> 状态上报了，所以**实体可能一直停在"可用"状态直到 HA 重启**。
>
> 只有"Bridge"那个连通性实体会立刻变成 off。
> 所以**判断整套系统死活要看 `binary_sensor.*_bridge`，不要看设备实体是否变灰**。
>
> 修法是在 `_on_bridge_state` 里除了发 `SIGNAL_BRIDGE_UPDATED`，
> 再对每个已知 MAC 发一遍 `SIGNAL_DEVICE_UPDATED`。当前版本没做。

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
    known: set[str] = set()

    @callback
    def _discover(entry_id: str, mac: str) -> None:
        if entry_id != entry.entry_id:
            return
        dev = hub.devices.get(mac)
        if not dev or "<cap>" not in dev.caps:
            return
        uid = f"{mac}_<cap>"
        if uid in known:
            return
        known.add(uid)
        async_add_entities([EspNow<X>(hub, dev)])

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_DEVICE_UPDATED, _discover)
    )
    for mac in list(hub.devices):
        _discover(entry.entry_id, mac)
```

三个要点：

| 要点 | 说明 |
|---|---|
| **`known` 是闭包里的 set** | 它防止重复创建。**不在 Hub 里，也不持久化** —— HA 重启后重新开始，靠 `unique_id` 让 HA 的实体注册表去重 |
| **先注册信号，再扫一遍现有设备** | 顺序很重要：如果先扫再注册，扫描和注册之间到达的消息会丢 |
| **`entry.async_on_unload`** | 卸载 entry 时自动退订，不会泄漏回调 |

`_discover` 会在**每一条 MQTT 消息**上被调用（七个平台各一次），
大部分时候立刻因为 `uid in known` 返回。这个开销可以忽略。

条件的差异见 [entities.md](entities.md#1-caps--平台映射)。
只有两个平台不是简单的 `"<cap>" in caps`：

- `switch.py`：`"switch" in caps and "light" not in caps`
  （被识别成灯的设备不再出 Switch 实体）
- `sensor.py`：`wanted = set(dev.caps) | {"hop", "node_role"}`，
  外加 rssi，然后对测量类 key 再要求它真的在 caps 里

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

实际上只有一个 Hub，这个循环是防御性的。

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

### 8.5 只允许一个 entry

`config_flow.py`：

```python
async def async_step_user(self, user_input=None):
    if self._async_current_entries():
        return self.async_abort(reason="already_configured")
    if mqtt.DOMAIN not in self.hass.config.components:
        return self.async_abort(reason="mqtt_not_ready")
    ...
    await self.async_set_unique_id(DOMAIN)
    self._abort_if_unique_id_configured()
```

两道 abort：

| reason | 何时 | 提示文本（`strings.json`） |
|---|---|---|
| `already_configured` | 已经有一个 entry | "ESP-NOW 2 MQTT is already configured" |
| `mqtt_not_ready` | HA 里还没配 MQTT 集成 | "MQTT integration is not set up. Add MQTT first." |

`unique_id` 被设成域名本身，加上 `_async_current_entries()` 检查，
**双重保证只有一个 entry**。

> **所以一个 HA 实例只能接一个 Bridge。** 想接两个协调器
> （比如两个楼层各一个），当前版本做不到——即使它们用不同的 base topic。
> 要支持得去掉 `_async_current_entries()` 检查并把 `unique_id` 改成
> base topic。`hass.data[DOMAIN]` 已经是按 `entry_id` 索引的，
> Hub 层面本来就支持多实例。

配置项只有一个：**base topic**。默认 `espnow2mqtt`，
输入时会 `.strip().rstrip("/")`。

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
甚至可能和别的集成的设备意外合并。

Bridge 那个设备是由 `EspNowBridgeBinary` 单独声明的：

```python
DeviceInfo(
    identifiers={(DOMAIN, "bridge")},
    name="ESP-NOW Coordinator",
    manufacturer="espnow2mqtt",
    model="USB Coordinator Bridge",
)
```

**注意它没有 `sw_version`**——因为 `bridge_info` 从未被填充
（[§3.4](#34-没有订阅-bridgeinfo)）。补上那个订阅之后就可以把
协调器的固件版本和信道显示在这里。

---

## 相关文档

- [state-flow.md](state-flow.md) — 一条 MQTT 消息的完整旅程，实体怎么被创建
- [entities.md](entities.md) — caps → 平台映射，每个实体的字段和单位换算
- [usage.md](usage.md) — 服务、自动化、模板
- [troubleshooting.md](troubleshooting.md) — 按症状排查
- [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) — 本集成读写的每个主题的权威定义
- [host 仓库 docs/bridge.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/bridge.md) — 上游的状态合并逻辑
