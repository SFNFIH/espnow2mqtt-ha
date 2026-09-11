# 实体参考

这一篇回答两个问题：

1. **我的设备会在 HA 里出现哪些实体？** → [§1 caps → 平台映射](#1-caps--平台映射)
2. **每个实体读哪个字段、发什么命令、怎么换算？** → [§3 起的各平台章节](#3-light)

前置知识：`caps` 是怎么算出来的见
[state-flow.md §3.4](state-flow.md#34-caps-推断三级-fall-through)；
每个字段在设备侧是怎么产生的见
[device 仓库 docs/reporting.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/reporting.md)。

目录：

1. [caps → 平台映射](#1-caps--平台映射)
2. [实体命名与 unique_id](#2-实体命名与-unique_id)
3. [Light](#3-light)
4. [Switch](#4-switch)
5. [Sensor](#5-sensor)
6. [Binary Sensor](#6-binary-sensor)
7. [Fan](#7-fan)
8. [Cover](#8-cover)
9. [Lock](#9-lock)
10. [Climate](#10-climate)
11. [Bridge 连通性实体](#11-bridge-连通性实体)
12. [按设备类型看会出什么](#12-按设备类型看会出什么)

---

## 1. caps → 平台映射

| `cap` | 平台 | 实体类 | 创建条件（`_discover` 里） |
|---|---|---|---|
| `light` | light | `EspNowLight` | `"light" in caps` |
| `switch` | switch | `EspNowSwitch` | `"switch" in caps` **且 `"light" not in caps`** |
| `fan` | fan | `EspNowFan` | `"fan" in caps` |
| `cover` | cover | `EspNowCover` | `"cover" in caps` |
| `lock` | lock | `EspNowLock` | `"lock" in caps` |
| `climate` | climate | `EspNowClimate` | `"climate" in caps` |
| `contact` | binary_sensor | `EspNowBinary` | `"contact" in caps` |
| `occupancy` | binary_sensor | `EspNowBinary` | `"occupancy" in caps` |
| `motion` | binary_sensor | `EspNowBinary` | `"motion" in caps` |
| `smoke` | binary_sensor | `EspNowBinary` | `"smoke" in caps` |
| `carbon_monoxide` | binary_sensor | `EspNowBinary` | `"carbon_monoxide" in caps` |
| `temperature` | sensor | `EspNowSensor` | `"temperature" in caps` |
| `humidity` | sensor | `EspNowSensor` | `"humidity" in caps` |
| `pressure` | sensor | `EspNowSensor` | `"pressure" in caps` |
| `illuminance` | sensor | `EspNowSensor` | `"illuminance" in caps` |
| `power` | sensor | `EspNowSensor` | `"power" in caps` |
| `energy` | sensor | `EspNowSensor` | `"energy" in caps` |
| — | sensor | `EspNowSensor` | **无条件**：`hop`、`node_role` |
| — | sensor | `EspNowSensor` | `dev.rssi is not None or "rssi" in dev.state` → `rssi` |

### 1.1 `button` cap 不产生任何实体

`hub.py` 的 caps 推断列表里有 `"button"`，但**没有任何平台处理它**：

- `SENSOR_SPECS` 里没有 `button`
- `BINARY_SPECS` 里没有 `button`
- 也没有 `event` 平台

所以一个报 `{"button":"single","caps":["button"]}` 的设备在 HA 里
**只会出现三个诊断实体**（hop / node_role / rssi），按键事件拿不到。

想用的话有两条路：

1. 在 HA 里直接订阅 MQTT 主题做自动化
   （见 [usage.md §6](usage.md#6-绕过集成直接用-mqtt)）
2. 改代码：给 `sensor.py` 的 `SENSOR_SPECS` 加一条 `"button"`，
   或者更正确地实现一个 `event` 平台

### 1.2 `light` 和 `switch` 互斥

Hub 在 `_on_device_state` 里做了两件事（见
[state-flow.md §3.5](state-flow.md#35-灯优先于开关)）：

1. payload 里有 `brightness` / `color_temp` / `level` ⇒ 加 `light` cap
2. 同时有 `light` 和 `switch` ⇒ **删掉 `switch`**

配合 `switch.py` 的 `"light" not in dev.caps` 条件，一个调光灯只出
**Light** 实体。

**但如果 Switch 实体在亮度字段到达之前就建好了，它不会被删除**——
你会看到同一个设备上有 `switch.x_switch` 和 `light.x_light` 两个实体。
见 [state-flow.md §6](state-flow.md#6-实体只增不减)。

### 1.3 诊断实体总是有

`sensor.py`：

```python
wanted = set(dev.caps) | {"hop", "node_role"}
if dev.rssi is not None or "rssi" in dev.state:
    wanted.add("rssi")
```

所以**任何设备**（哪怕 caps 完全是空的）都至少有
`Mesh Hop` 和 `Node Role` 两个诊断实体。
`RSSI` 要等 `bridge/devices` 到达（那是 RSSI 的唯一来源）。

这三个都带 `EntityCategory.DIAGNOSTIC`，在 HA 的设备页会被折叠到
"诊断"区，不占主界面。

### 1.4 测量类 key 的额外过滤

```python
_MEASUREMENT_KEYS = ("temperature", "humidity", "pressure", "illuminance", "power", "energy")
...
if key in _MEASUREMENT_KEYS and key not in dev.caps:
    continue
```

看起来冗余（`wanted` 就是从 `dev.caps` 来的），但它挡住了一种情况：
如果以后有人往 `wanted` 里加了别的来源，测量类实体仍然只在
caps 明确声明时才创建。防御性代码。

---

## 2. 实体命名与 unique_id

```python
_attr_has_entity_name = True        # entity.py
_attr_unique_id = f"{device.mac}_{key}"
```

`has_entity_name = True` 意味着 HA 会把**设备名和实体名拼起来**显示。
所以各平台的 `_attr_name` 都是短名：

| 平台 | `_attr_name` | 设备叫 `Living Room` 时显示为 |
|---|---|---|
| light | `"Light"` | Living Room Light |
| switch | `"Switch"` | Living Room Switch |
| fan | `"Fan"` | Living Room Fan |
| cover | `"Cover"` | Living Room Cover |
| lock | `"Lock"` | Living Room Lock |
| climate | `"Thermostat"` | Living Room Thermostat |
| sensor | `"Temperature"` / `"Humidity"` / `"Pressure"` / `"Illuminance"` / `"Power"` / `"Energy"` / `"Mesh Hop"` / `"RSSI"` / `"Node Role"` | Living Room Temperature |
| binary_sensor | `"Contact"` / `"Occupancy"` / `"Motion"` / `"Smoke"` / `"Carbon Monoxide"` | Living Room Contact |
| binary_sensor（Bridge） | `"Bridge"` | ESP-NOW Coordinator Bridge |

**实体 ID**（`light.living_room_light` 这种）由 HA 从显示名自动生成，
生成之后就固定在实体注册表里，改设备名不会改实体 ID。

**`unique_id` 里是 MAC**，所以：

| 变化 | 实体会怎样 |
|---|---|
| 改了固件里的 `name`（slug 变了） | **实体不变**（unique_id 用的是 MAC）。但 MQTT 主题变了，需要清理旧的 retained 主题，见 [troubleshooting.md](troubleshooting.md#5-实体是灰的) |
| 换了一块 C3（MAC 变了） | **全新的设备和实体**。旧的留在 HA 里不可用 |
| 重装集成 | 实体 ID 和历史数据保留（unique_id 匹配） |

`slug:` 占位设备的 unique_id 是 `slug:relay1_switch` 这种，
所以它和真设备的实体是两套。见
[state-flow.md §3.3](state-flow.md#33-slug-占位设备)。

---

## 3. Light

```python
class EspNowLight(EspNowEntity, LightEntity):
    _attr_name = "Light"
    _attr_min_color_temp_kelvin = 2000
    _attr_max_color_temp_kelvin = 6500
```

| HA 属性 | 读哪个字段 | 换算 |
|---|---|---|
| `is_on` | `switch` | `str(...).upper() == "ON"` |
| `brightness` | `brightness`，回退到 `level` | **0–254 → 0–255** |
| `color_temp_kelvin` | `color_temp` | **mired → Kelvin** |

| HA 操作 | 发出的 payload |
|---|---|
| `turn_on()` | `{"switch":"ON"}` |
| `turn_on(brightness=B)` | `{"switch":"ON","brightness":<1-254>}` |
| `turn_on(color_temp_kelvin=K)` | `{"switch":"ON","color_temp":<mired>}` |
| `turn_off()` | `{"switch":"OFF"}` |

亮度和色温可以在一条命令里同时给。

### 3.1 亮度：0–254 ↔ 0–255

固件用的是 Matter 的 `CurrentLevel` 范围 **0–254**，HA 用 **0–255**。

**读（固件 → HA）**

```python
raw = self._device.state.get("brightness", self._device.state.get("level"))
level = int(raw)
return max(0, min(255, int(round(level * 255 / 254)))) if level else 0
```

| 固件 `brightness` | HA `brightness` |
|---|---|
| 0 | 0（`if level else 0` 短路） |
| 1 | 1 |
| 127 | 128 |
| 128 | 129 |
| 254 | 255 |

**写（HA → 固件）**

```python
bri = int(kwargs[ATTR_BRIGHTNESS])
level = max(1, min(254, int(round(bri * 254 / 255))))
```

| HA `brightness` | 固件 `brightness` |
|---|---|
| 1 | 1 |
| 128 | 128 |
| 255 | 254 |

**`max(1, ...)` 保证写下去的亮度永远 ≥ 1**——HA 里把亮度拉到 0
应该走 `turn_off()` 而不是"亮度 0"，这个下限避免了"灯开着但亮度 0"
这种既开又关的状态。

> **往返可能差 1。** `round(round(x*254/255)*255/254)` 在大多数值上
> 是恒等的，但个别值会偏 1（比如 HA 129 → 固件 129 → HA 130）。
> 视觉上不可见，但如果你在自动化里做"亮度等于 N"的精确比较，
> 会偶尔不成立。用范围比较（`>=` / `<=`）而不是 `==`。

### 3.2 色温：mired ↔ Kelvin

```python
def _mireds_to_kelvin(mireds: int) -> int:
    mireds = max(1, int(mireds))
    return int(round(1_000_000 / mireds))

def _kelvin_to_mireds(kelvin: int) -> int:
    kelvin = max(1, int(kelvin))
    return int(round(1_000_000 / kelvin))
```

固件用 **mired**（Matter 的 `ColorTemperatureMireds`），HA 用 **Kelvin**。
`max(1, ...)` 防除零。

| mired | Kelvin |
|---|---|
| 153 | 6536 |
| 250 | 4000 |
| 370 | 2703 |
| 500 | 2000 |

声明的范围是 **2000–6500 K**，对应 **154–500 mired**：

```python
_attr_min_color_temp_kelvin = 2000
_attr_max_color_temp_kelvin = 6500
```

> **这两个值是硬编码的，不看设备实际支持的范围。**
> 固件的 ColorControl cluster 有自己的 min/max mired 属性，
> 但集成不读它们。如果你的灯只支持 2700–6500 K，
> HA 的滑条还是会显示到 2000 K，拉过去设备会自己夹到能力范围内。
>
> 影响很小（设备侧会夹），但 UI 上会有一小段"拉了没变化"的死区。

### 3.3 色彩模式的判定有个时序坑

```python
def __init__(self, hub, device):
    super().__init__(hub, device, "light")
    modes: set[ColorMode] = {ColorMode.BRIGHTNESS}
    if "color_temp" in device.state or "color_temp" in device.caps:
        modes = {ColorMode.COLOR_TEMP}
    self._attr_supported_color_modes = modes
    self._attr_color_mode = next(iter(modes))
```

**色彩模式是在实体创建的那一刻决定的，之后不会自动更新。**

| 创建时 `state` 里有 `color_temp`？ | 支持的模式 |
|---|---|
| 有 | `{COLOR_TEMP}`（HA 的 COLOR_TEMP 隐含支持亮度） |
| 没有 | `{BRIGHTNESS}`——**只有亮度滑条，没有色温滑条** |

所以如果实体是在一条"被 160 字节挤掉了 `color_temp`"的上报上建出来的，
它会永远是纯调光灯。

`async_turn_on` 里有个运行时补救：

```python
if ATTR_COLOR_TEMP_KELVIN in kwargs:
    payload["color_temp"] = _kelvin_to_mireds(kelvin)
    self._attr_color_mode = ColorMode.COLOR_TEMP
    self._attr_supported_color_modes = {ColorMode.COLOR_TEMP}
```

但这是**鸡生蛋**——用户得先能设色温，才能触发这段代码，
而色温滑条在 UI 上根本没出现。

**实际解法：重启 HA。** 重启后实体重新构造，这次 `dev.state`
是从 retained 的 `<slug>/state` 恢复的，通常已经包含 `color_temp`。

更彻底的修法是在 `_handle_update` 里重算 `supported_color_modes`，
当前版本没做。

---

## 4. Switch

```python
class EspNowSwitch(EspNowEntity, SwitchEntity):
    _attr_name = "Switch"
```

最简单的平台，整个类 17 行。

| HA 属性/操作 | 字段 / payload |
|---|---|
| `is_on` | `str(state.get("switch", "OFF")).upper() == "ON"` |
| `turn_on()` | `{"switch":"ON"}` |
| `turn_off()` | `{"switch":"OFF"}` |

**默认值是 `"OFF"`**，所以在第一条状态到达之前实体显示为 off
（而不是 unknown）。这对 UI 更友好，但意味着"off"可能是"还不知道"。
要区分就看实体的 `available` 属性。

创建条件是 `"switch" in caps and "light" not in caps`，见
[§1.2](#12-light-和-switch-互斥)。

---

## 5. Sensor

`SENSOR_SPECS` 是一张表驱动的字典：

| key | 名称 | device_class | state_class | 单位 | 类别 |
|---|---|---|---|---|---|
| `temperature` | Temperature | `TEMPERATURE` | `MEASUREMENT` | °C | — |
| `humidity` | Humidity | `HUMIDITY` | `MEASUREMENT` | % | — |
| `pressure` | Pressure | `PRESSURE` | `MEASUREMENT` | hPa | — |
| `illuminance` | Illuminance | `ILLUMINANCE` | `MEASUREMENT` | lx | — |
| `power` | Power | `POWER` | `MEASUREMENT` | W | — |
| `energy` | Energy | `ENERGY` | **`TOTAL_INCREASING`** | Wh | — |
| `hop` | Mesh Hop | — | — | — | `DIAGNOSTIC` |
| `rssi` | RSSI | `SIGNAL_STRENGTH` | — | dBm | `DIAGNOSTIC` |
| `node_role` | Node Role | — | — | — | `DIAGNOSTIC` |

### 5.1 没有单位换算

**固件已经换算过了。** `temperature` / `humidity` / `pressure` /
`power` / `energy` 在设备侧序列化时就除过了
（÷100 / ÷100 / ÷10 / ÷1000 / ÷1000），MQTT 上就是人类单位。
集成只做 `float()`：

```python
if key in _MEASUREMENT_KEYS:
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
```

换算失败返回 `None` → HA 显示 `unknown`，不会报错。

### 5.2 `energy` 是 `TOTAL_INCREASING`

这让它能进 HA 的**能源面板**。语义是"单调递增的累计值，
归零时 HA 自动处理为一次重启"。

设备侧的 `ENERGY_MWH` 属性是持久化到 NVS 的（device 仓库
`docs/persistence.md`），所以设备断电重启不会归零。
只有 `erase-flash` 才会。

### 5.3 三个诊断量的取值有回退

```python
if key == "rssi":
    return self._device.rssi if self._device.rssi is not None else self._device.state.get("rssi")
if key == "hop":
    return self._device.hop if self._device.hop is not None else self._device.state.get("hop")
if key == "node_role":
    return self._device.node_role or self._device.state.get("node_role")
```

先看 `EspNowDevice` 上的专有字段（来自 `bridge/devices`），
没有再回退到 `state` 字典（来自 `<slug>/state`）。

| 量 | 主来源 | 回退 |
|---|---|---|
| `rssi` | `bridge/devices` | `state["rssi"]`（**当前上游不会发这个**，纯防御） |
| `hop` | `bridge/devices` 和 `<slug>/state` 都会写 `dev.hop` | 同上 |
| `node_role` | 两个都会写 | 同上 |

RSSI 的刷新频率 = `bridge/devices` 的重写频率。Bridge 每收到一条
`device` 行就重写，即**每个设备每 30 秒一次**。

### 5.4 `SENSOR_SPECS` 里的 precision 字段没被用

每条 spec 是 6 元组，最后一个是精度：

```python
name, device_class, state_class, unit, category, _prec = SENSOR_SPECS[key]
```

`_prec` 解包出来就**再也没有用过**（下划线前缀已经暗示了）。
所以温度显示的小数位数由 HA 根据 `device_class` 自己决定，
而不是这张表里写的 1 位。

想生效得加 `self._attr_suggested_display_precision = _prec`。
当前版本没做。

---

## 6. Binary Sensor

```python
BINARY_SPECS: dict[str, tuple[str, BinarySensorDeviceClass]] = {
    "contact":         ("Contact",         BinarySensorDeviceClass.DOOR),
    "occupancy":       ("Occupancy",       BinarySensorDeviceClass.OCCUPANCY),
    "motion":          ("Motion",          BinarySensorDeviceClass.MOTION),
    "smoke":           ("Smoke",           BinarySensorDeviceClass.SMOKE),
    "carbon_monoxide": ("Carbon Monoxide", BinarySensorDeviceClass.CO),
}
```

取值逻辑对五个都一样：

```python
@property
def is_on(self) -> bool:
    return str(self._device.state.get(self._key, "OFF")).upper() == "ON"
```

**依赖 Hub 已经归一化过了。** Hub 在 `_on_device_state` 里把这五个字段
统一成 `"ON"` / `"OFF"`：

| 认作 ON 的输入 | 备注 |
|---|---|
| `ON` / `1` / `TRUE` / `OPEN` / `DETECTED` | 大小写无关 |

所以设备发 `"OPEN"` 或 `"DETECTED"` 也能正常工作。归一化表见
[state-flow.md §3.8](state-flow.md#38-归一化表)。

### `contact` 的 device_class 是 `DOOR`

意味着 HA 里显示成"打开 / 关闭"而不是"检测到 / 清除"。
如果你的门磁装在窗户上想显示成"窗户"，在 HA 里改实体的
device_class（**Settings → Entities → 该实体 → 齿轮 → 显示为**）。

---

## 7. Fan

```python
PRESET_MODES = ["off", "low", "medium", "high", "on", "auto", "smart"]

class EspNowFan(EspNowEntity, FanEntity):
    _attr_name = "Fan"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF
    )
    _attr_preset_modes = PRESET_MODES
    _attr_speed_count = 100
```

| HA 属性 | 读哪个字段 | 逻辑 |
|---|---|---|
| `is_on` | `fan_mode`，回退 `percentage` | 见 [§7.1](#71-is_on-的三级判断) |
| `percentage` | `percentage` | 直接 `int`，夹到 0–100 |
| `preset_mode` | `fan_mode` | 在 `PRESET_MODES` 里就用，否则 `"off"` |

| HA 操作 | 发出的 payload |
|---|---|
| `turn_on()` | `{"fan_mode":"on","percentage":<当前 or 50>}` |
| `turn_on(preset_mode=M)` | `{"fan_mode":M}` |
| `turn_on(percentage=P)` | `{"percentage":P,"fan_mode":"on" if P else "off"}` |
| `turn_off()` | `{"fan_mode":"off","percentage":0}` |
| `set_percentage(P)` | `{"percentage":P,"fan_mode":"off" if P==0 else "on"}` |
| `set_preset_mode(M)` | `{"fan_mode":M}` |

`_attr_speed_count = 100` 让 HA 显示 1% 步进的滑条
（而不是按档位）。固件的 `PERCENT_SETTING` 就是 0–100，所以是 1:1 的。

### 7.1 `is_on` 的三级判断

```python
mode = str(self._device.state.get("fan_mode", "off")).lower()
if mode in ("off", ""):
    return False
if mode in ("on", "auto", "smart", "low", "medium", "high"):
    return True
return (self.percentage or 0) > 0
```

先看 `fan_mode`，认不出来的模式才回退到百分比。
这样即使固件发了个新的模式名，实体也不会乱。

### 7.2 集成和固件都在维护一致性

**两边都会保证 `fan_mode` 和 `percentage` 一致，所以一条命令可能触发设备侧两次写回调。**

集成侧：`set_percentage(0)` 会一起发 `fan_mode: "off"`。

固件侧（device 仓库 `en2m_model.c`）：

| 收到的命令 | 设备侧实际发生 |
|---|---|
| `{"fan_mode":"off"}` | 写 `FAN_MODE=OFF`，**再**写 `PERCENT_SETTING=0` |
| `{"percentage":0}` | 写 `PERCENT_SETTING=0`，**再**写 `FAN_MODE=OFF` |
| `{"percentage":50}`（原来 off） | 写 `PERCENT_SETTING=50`，**再**写 `FAN_MODE=ON` |

所以集成发 `{"percentage":0,"fan_mode":"off"}` 时，设备侧的写回调
可能被调用 **3～4 次**。如果你在写回调里有非幂等的副作用，要自己去重。

### 7.3 `smart` 模式固件可能不支持

`PRESET_MODES` 里的 `"smart"` 对应 Matter FanMode 的 `Smart(6)`。
`en2m` 组件的枚举里有它，但**设备侧的写回调可能拒绝**
（取决于你的固件实现）。

表现：在 HA 里选了 smart，命令发出去、设备 ACK 了、但状态没变回 smart。
见 [troubleshooting.md §4.4](troubleshooting.md#44-命令-ack-了但状态没变)。

---

## 8. Cover

**这是整个集成最容易搞错的一个平台，因为 HA 和固件对"位置"的定义是反的。**

```python
_attr_supported_features = (
    CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    | CoverEntityFeature.STOP | CoverEntityFeature.SET_POSITION
)
```

### 8.1 位置的反转

| | 0 表示 | 100 表示 |
|---|---|---|
| **固件 `position`**（Matter `CurrentPositionLiftPercent`） | 完全**打开** | 完全**关闭** |
| **HA `current_cover_position`** | 完全**关闭** | 完全**打开** |

所以代码里到处是 `100 - x`：

```python
def _closed_pct(self) -> int:
    raw = self._device.state.get("position")
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        cover = str(self._device.state.get("cover", "OPEN")).upper()
        return 100 if cover == "CLOSED" else 0

@property
def current_cover_position(self) -> int | None:
    # HA: 0 = closed, 100 = open
    return 100 - self._closed_pct()

@property
def is_closed(self) -> bool:
    return self._closed_pct() >= 95

async def async_set_cover_position(self, **kwargs) -> None:
    open_pct = int(kwargs.get("position", 0))
    closed = max(0, min(100, 100 - open_pct))
    await self._hub.async_publish_set(self._device, {"position": closed})
```

对照表：

| 物理状态 | 固件 `position` | HA `current_cover_position` | `is_closed` |
|---|---:|---:|:-:|
| 全开 | 0 | 100 | ✗ |
| 开 70% | 30 | 70 | ✗ |
| 半开 | 50 | 50 | ✗ |
| 关 95% | 95 | 5 | **✓** |
| 全关 | 100 | 0 | ✓ |

> **在 MQTT 上手工发命令时一定要注意这个反转。**
>
> ```bash
> # 想让窗帘开到 30%（HA 语义）
> mosquitto_pub -t espnow2mqtt/bedroom/set -m '{"position":70}'
> #                                                        ^^ 100-30
> ```
>
> 也就是说 [homeassistant.md](homeassistant.md) 里写的
> `{"position":50}` 恰好是半开（50 两边一样），所以那个例子看不出问题。
> 非 50 的值一定要换算。

### 8.2 `is_closed` 的 95 阈值

`_closed_pct() >= 95` 而不是 `== 100`，是为了容忍电机的机械误差——
关到 96% 就该算关好了。

**这个阈值和固件侧推导 `cover` 字段用的是同一个值**
（device 仓库 `en2m_model.c` 里 `v >= 95 ? "CLOSED" : "OPEN"`），
所以两边判断一致。

### 8.3 `position` 缺失时的回退

`_closed_pct()` 的 `except` 分支读 `cover` 字段
（`"OPEN"` / `"CLOSED"`），映射成 0 / 100。

这让**不支持位置反馈的窗帘**（只报开/关）也能工作，
只是 HA 的位置滑条会在 0 和 100 之间跳。

注意回退分支的默认是 `"OPEN"` → 0（全开）。
所以一个既没有 `position` 也没有 `cover` 字段的设备，
在 HA 里显示为"全开"而不是 unknown。

### 8.4 命令用的是字符串不是位置

| HA 操作 | payload | 备注 |
|---|---|---|
| `open_cover()` | `{"cover":"OPEN"}` | 不是 `{"position":0}` |
| `close_cover()` | `{"cover":"CLOSE"}` | 注意是 `CLOSE` 不是 `CLOSED`（命令 vs 状态） |
| `stop_cover()` | `{"cover":"STOP"}` | |
| `set_cover_position(P)` | `{"position":100-P}` | 反转 |

`open` / `close` / `stop` 用字符串命令而不是位置，
是为了让固件走 `WindowCovering` 的 `open`/`close`/`stop` 命令
（可能有额外的电机逻辑，比如 STOP 要立刻断电），
而不是"移动到位置 0"。

`is_opening` / `is_closing` **没有实现**，所以 HA 里看不到
"正在打开"的中间状态，只有"打开 / 关闭 / 位置 N%"。

---

## 9. Lock

```python
class EspNowLock(EspNowEntity, LockEntity):
    _attr_name = "Lock"

    @property
    def is_locked(self) -> bool:
        return str(self._device.state.get("lock", "UNLOCKED")).upper() == "LOCKED"

    async def async_lock(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"lock": "LOCK"})

    async def async_unlock(self, **kwargs) -> None:
        await self._hub.async_publish_set(self._device, {"lock": "UNLOCK"})
```

| | 状态值 | 命令值 |
|---|---|---|
| 锁上 | `"LOCKED"` | `"LOCK"` |
| 打开 | `"UNLOCKED"` | `"UNLOCK"` |

**状态和命令的词形不同**（`LOCKED` vs `LOCK`）。
Hub 的归一化会把 `LOCK` 也认成 `LOCKED`，所以即使固件把命令值
回报成状态也不会出错（见
[state-flow.md §3.8](state-flow.md#38-归一化表)）。

默认值 `"UNLOCKED"`——第一条状态到达前显示为已解锁。
**对门锁来说这个默认方向偏不安全**，但它只影响 UI 显示，
不影响实际锁的状态。要区分"真的开着"和"还不知道"，看 `available`。

`is_jammed` / `is_locking` / `is_unlocking` **没有实现**，
所以没有中间状态和卡住告警。`LockEntityFeature.OPEN`（门闩）也没有。

---

## 10. Climate

```python
_MODE_MAP = {
    "off": HVACMode.OFF,
    "auto": HVACMode.AUTO,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "fan_only": HVACMode.FAN_ONLY,
}
_MODE_REV = {v: k for k, v in _MODE_MAP.items()}

class EspNowClimate(EspNowEntity, ClimateEntity):
    _attr_name = "Thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_hvac_modes = list(_MODE_MAP.values())
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5
```

| HA 属性 | 读哪个字段 | 备注 |
|---|---|---|
| `hvac_mode` | `hvac_mode` | 通过 `_MODE_MAP` 映射，**认不出来的一律变 `OFF`** |
| `current_temperature` | `current_temperature`，**回退到 `temperature`** | `float()`，失败返回 `None` |
| `target_temperature` | `target_temperature` | 同上 |

| HA 操作 | payload |
|---|---|
| `set_hvac_mode(M)` | `{"hvac_mode":<_MODE_REV[M] or "off">}` |
| `set_temperature(temperature=T)` | `{"target_temperature":<float>}` |

### 10.1 只支持 5 种模式

`_MODE_MAP` 只有 off / auto / cool / heat / fan_only。

Matter 的 `SystemMode` 还有 `dry(8)`、`precooling(5)`、
`emergency_heat(6)`、`sleep(9)`。**如果固件报了这些值，
`_MODE_MAP.get(raw, HVACMode.OFF)` 会让 HA 显示成 OFF**——
而设备实际在运行。

表现：温控器在 HA 里显示"关闭"但房间在制冷。
要支持就往 `_MODE_MAP` 里加条目
（`HVACMode.DRY`、`HVACMode.HEAT_COOL` 等）。

### 10.2 `current_temperature` 会回退到 `temperature`

```python
val = self._device.state.get("current_temperature", self._device.state.get("temperature"))
```

固件的温控器 cluster 报的是 `current_temperature`
（来自 `LOCAL_TEMPERATURE` 属性）。回退到 `temperature` 是为了兼容
"温控器设备同时挂了一个独立的温度传感器 cluster"的情况——
那种设备会报 `temperature` 而不是 `current_temperature`。

> **⚠️ 这个回退会和 Temperature sensor 实体抢同一个字段。**
> 如果设备的 caps 里同时有 `climate` 和 `temperature`，
> 你会得到一个 `climate.x_thermostat`（当前温度 = `temperature`）
> **和**一个 `sensor.x_temperature`（值 = 同一个 `temperature`）。
> 两个显示相同的值，不是 bug，只是冗余。

### 10.3 单个 setpoint

`supported_features` 只有 `TARGET_TEMPERATURE`，**没有 `TARGET_TEMPERATURE_RANGE`**。
所以 HA 里只有一个目标温度滑条，不是"制热下限 + 制冷上限"两个。

这和固件侧的行为对得上：固件存了两个 setpoint
（`OCCUPIED_HEATING_SETPOINT` 和 `OCCUPIED_COOLING_SETPOINT`），
但只上报"当前模式在追的那一个"，键固定叫 `target_temperature`
（device 仓库 `docs/reporting.md`）。

下行同理：`{"target_temperature":24}` 在 `cool` 模式下写制冷设定点，
其他模式下写制热设定点（见
[host 仓库 protocol/PROTOCOL.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/protocol/PROTOCOL.md)）。

> **所以先切模式再设温度。** 在 `heat` 模式下设 24 °C，
> 然后切到 `cool`，目标温度会跳回制冷设定点的旧值——
> 因为那是两个不同的存储位置。

### 10.4 温度范围是硬编码的

`min_temp = 5`、`max_temp = 35`、`step = 0.5`。
不看设备实际支持的范围（固件的 Thermostat cluster 有
`AbsMinHeatSetpointLimit` 之类的属性，集成不读）。

`step = 0.5` 和固件的精度对得上：固件内部用 ÷100 的定点整数，
所以 0.5 °C 能精确表示。

`ClimateEntityFeature` 里的 `FAN_MODE` / `PRESET_MODE` /
`SWING_MODE` / `TURN_ON` / `TURN_OFF` 都没有实现。
关掉温控器要用 `set_hvac_mode("off")`。

---

## 11. Bridge 连通性实体

```python
class EspNowBridgeBinary(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Bridge"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_should_poll = False

    def __init__(self, hub: EspNowHub) -> None:
        self._hub = hub
        self._attr_unique_id = f"{hub.entry.entry_id}_bridge"
```

| | |
|---|---|
| 实体 ID | 通常是 `binary_sensor.esp_now_coordinator_bridge` |
| `is_on` | `hub.bridge_online` |
| 数据源 | `<base>/bridge/state` 上的 `"online"` / `"offline"` |
| 挂在哪个设备 | 独立的 `ESP-NOW Coordinator`（`identifiers={(DOMAIN,"bridge")}`） |
| 可用性 | **永远可用**（不继承 `EspNowEntity`，没有 `available` 覆盖） |

它在 `binary_sensor.async_setup_entry` 里**无条件创建**，
不等任何 MQTT 消息：

```python
async_add_entities([EspNowBridgeBinary(hub)])
```

所以它总是存在，即使一个设备都没有。

### 这是判断整套系统死活的正确实体

因为 `SIGNAL_BRIDGE_UPDATED` **只被它订阅**，
`bridge_online` 变化时只有它会立刻刷新
（见 [architecture.md §6](architecture.md#6-dispatcher-信号)）。

普通设备实体的 `available` 逻辑上包含了 `bridge_online`，
但它们要等下一条 `SIGNAL_DEVICE_UPDATED` 才重算——而 Bridge 挂了
就不会再有状态上报，所以**设备实体可能一直停在"可用"**。

> **写自动化时：监控 `binary_sensor.*_bridge` 从 `on` 变 `off`，
> 不要监控某个设备实体变 unavailable。** 见
> [usage.md §4](usage.md#4-推荐的自动化)。

---

## 12. 按设备类型看会出什么

假设 `caps` 是设备正常上报的值（`en2m` 固件总是报显式 `caps`）。
每一行都额外有 `Mesh Hop` / `Node Role` / `RSSI` 三个诊断实体，表里省略。

| 设备（device 仓库的例程） | `caps` | HA 实体 |
|---|---|---|
| `relay_switch` | `["switch"]` | `switch.*_switch` |
| `dimmable_light` | `["light"]` | `light.*_light` |
| `smart_plug` | `["switch","power","energy"]` | `switch.*_switch`、`sensor.*_power`、`sensor.*_energy` |
| `th_sensor` | `["temperature","humidity"]` | `sensor.*_temperature`、`sensor.*_humidity` |
| `contact_sensor` | `["contact"]` | `binary_sensor.*_contact`（DOOR） |
| `occupancy_sensor` | `["occupancy"]` | `binary_sensor.*_occupancy` |
| `window_cover` | `["cover"]` | `cover.*_cover` |
| `door_lock` | `["lock"]` | `lock.*_lock` |
| `fan_controller` | `["fan"]` | `fan.*_fan` |
| `thermostat` | `["climate"]` | `climate.*_thermostat` |
| 烟感 | `["smoke"]` | `binary_sensor.*_smoke`（SMOKE） |
| CO 报警 | `["carbon_monoxide"]` | `binary_sensor.*_carbon_monoxide`（CO） |
| 气压计 | `["pressure"]` | `sensor.*_pressure` |
| 光照传感器 | `["illuminance"]` | `sensor.*_illuminance` |
| 按键 | `["button"]` | **只有诊断实体**（[§1.1](#11-button-cap-不产生任何实体)） |
| `router`（中继节点） | 通常没有 caps | 只有诊断实体 |

`router` 节点只出诊断实体是对的——它是纯中继，没有外设。
`Mesh Hop` 和 `RSSI` 正好是你想监控的东西。

---

## 相关文档

- [state-flow.md](state-flow.md) — caps 是怎么推断出来的，实体怎么被创建
- [architecture.md](architecture.md) — 实体基类、可用性、设备注册表层级
- [usage.md](usage.md) — 自动化和模板怎么用这些实体
- [troubleshooting.md](troubleshooting.md) — 实体没出来 / 值不对
- [device 仓库 docs/reporting.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/reporting.md) — 每个字段在设备侧怎么算出来的
- [device 仓库 docs/data-model.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/data-model.md) — cluster / attribute / command 全表
