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
11. [Event（按钮）](#11-event按钮)
12. [Bridge 连通性实体](#12-bridge-连通性实体)
13. [按设备类型看会出什么](#13-按设备类型看会出什么)

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
| `button` | **event** | `EspNowButtonEvent` | `"button" in caps` |
| — | sensor | `EspNowSensor` | **无条件**：`hop`、`node_role` |
| — | sensor | `EspNowSensor` | `dev.rssi is not None or "rssi" in dev.state` → `rssi` |

每个实体类还带一个 `_requires_cap`，值就是表里的 `cap`
（诊断实体是 `None`）。cap 消失时实体会据此自删，
见 [state-flow.md §6](state-flow.md#6-实体能增也能减)。

### 1.1 `light` 和 `switch` 互斥

Hub 在 `_on_device_state` 里做了两件事（见
[state-flow.md §3.5](state-flow.md#35-灯优先于开关)）：

1. payload 里有 `brightness` / `color_temp` / `level` ⇒ 加 `light` cap
2. 同时有 `light` 和 `switch` ⇒ **删掉 `switch`**

配合 `switch.py` 的 `"light" not in dev.caps` 条件，一个调光灯只出
**Light** 实体。

如果 Switch 实体在亮度字段到达之前就建好了，它会在升级发生时**自删**
（`EspNowSwitch._requires_cap = "switch"`，而 `switch` 刚被从 caps 里拿掉）。
见 [state-flow.md §6](state-flow.md#6-实体能增也能减)。

### 1.2 诊断实体总是有

`sensor.py`：

```python
wanted = {"hop", "node_role"}
wanted.update(cap for cap in device.caps if cap in SENSOR_SPECS)
if device.rssi is not None or "rssi" in device.state:
    wanted.add("rssi")
```

所以**任何设备**（哪怕 caps 完全是空的）都至少有
`Mesh Hop` 和 `Node Role` 两个诊断实体。
`RSSI` 要等 `bridge/devices` 到达（那是 RSSI 的唯一来源）。

这三个都带 `EntityCategory.DIAGNOSTIC`，在 HA 的设备页会被折叠到
"诊断"区，不占主界面。也正因为它们不依赖任何能力，
它们的 `_requires_cap` 是 `None`，永远不会自删。

### 1.3 测量量 vs 诊断量

`SENSOR_SPECS` 里每条规格都有一个 `measurement` 标志：

```python
@dataclass(frozen=True)
class SensorSpec:
    name: str
    device_class: SensorDeviceClass | None = None
    state_class: SensorStateClass | None = None
    unit: str | None = None
    category: EntityCategory | None = None
    precision: int | None = None
    measurement: bool = False

_MEASUREMENT_KEYS = tuple(k for k, s in SENSOR_SPECS.items() if s.measurement)
```

测量量只在 caps 明确声明时创建，并且 `_requires_cap` 设成自己的键；
诊断量两者都不做。这个区分只写一处（规格里的那个布尔值），
上面那行 `_MEASUREMENT_KEYS` 是从它推出来的，不会和规格表脱节。

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

### 3.3 色彩模式是每次读时判定的

```python
def _is_cct(self) -> bool:
    return (
        "color_temp" in self._device.state
        or "color_temp" in self._device.caps
        or str(self._device.state.get("color_mode", "")).lower() == "color_temp"
    )

@property
def supported_color_modes(self) -> set[ColorMode]:
    return {ColorMode.COLOR_TEMP} if self._is_cct() else {ColorMode.BRIGHTNESS}

@property
def color_mode(self) -> ColorMode:
    return ColorMode.COLOR_TEMP if self._is_cct() else ColorMode.BRIGHTNESS
```

| `state` 里有 `color_temp` 或 `color_mode: "color_temp"`？ | 支持的模式 |
|---|---|
| 有 | `{COLOR_TEMP}`（HA 的 COLOR_TEMP 隐含支持亮度） |
| 没有 | `{BRIGHTNESS}`——只有亮度滑条 |

两种模式不能并列：HA 里 `COLOR_TEMP` 已经含亮度，把 `BRIGHTNESS`
和它放一起是非法组合。

因为是属性而不是构造时的快照，**一条晚到的带 `color_temp` 的上报
就能让色温滑条出现**，不需要重启 HA。`color_mode` 这个键也算，
因为 `en2m` 的 ColorControl cluster 会同时发
`{"color_mode":"color_temp","color_temp":370}`。

> 0.3.x 里这两个值是在 `__init__` 里算一次就定死的。
> 如果实体是在一条"被 160 字节挤掉了 `color_temp`"的上报上建出来的，
> 它会**永远**是纯调光灯。`async_turn_on` 里有段运行时补救，
> 但那是鸡生蛋——用户得先能设色温才能触发它，而色温滑条根本没出现。
> 唯一的解法是重启 HA 让实体重新构造。

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
[§1.2](#11-light-和-switch-互斥)。

---

## 5. Sensor

`SENSOR_SPECS` 是一张表驱动的字典：

| key | 名称 | device_class | state_class | 单位 | 类别 | 小数位 |
|---|---|---|---|---|---|:-:|
| `temperature` | Temperature | `TEMPERATURE` | `MEASUREMENT` | °C | — | 1 |
| `humidity` | Humidity | `HUMIDITY` | `MEASUREMENT` | % | — | 1 |
| `pressure` | Pressure | `PRESSURE` | `MEASUREMENT` | hPa | — | 1 |
| `illuminance` | Illuminance | `ILLUMINANCE` | `MEASUREMENT` | lx | — | 0 |
| `power` | Power | `POWER` | `MEASUREMENT` | W | — | 1 |
| `energy` | Energy | `ENERGY` | **`TOTAL_INCREASING`** | Wh | — | 2 |
| `hop` | Mesh Hop | — | — | — | `DIAGNOSTIC` | 0 |
| `rssi` | RSSI | `SIGNAL_STRENGTH` | — | dBm | `DIAGNOSTIC` | 0 |
| `node_role` | Node Role | — | — | — | `DIAGNOSTIC` | — |

"小数位"那一列就是 `SensorSpec.precision`，直接落到
`_attr_suggested_display_precision`。它是**建议值**：
用户在实体设置里改过之后，HA 的实体注册表会记住用户的选择并覆盖它。

### 5.1 没有单位换算

**固件已经换算过了。** `temperature` / `humidity` / `pressure` /
`power` / `energy` 在设备侧序列化时就除过了
（÷100 / ÷100 / ÷10 / ÷1000 / ÷1000），MQTT 上就是人类单位。
集成只做 `float()`：

```python
val = self._device.state.get(key)
if val is None:
    return None
try:
    return float(val)
except (TypeError, ValueError):
    return None
```

换算失败返回 `None` → HA 显示 `unknown`，不会报错。
（`hop` / `rssi` / `node_role` 在这段之前就已经 return 了，
所以走到这里的一定是测量量。）

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

### 5.4 规格是数据类，不是元组

```python
spec = SENSOR_SPECS[key]
self._attr_name = spec.name
self._attr_device_class = spec.device_class
self._attr_state_class = spec.state_class
self._attr_native_unit_of_measurement = spec.unit
self._attr_entity_category = spec.category
self._attr_suggested_display_precision = spec.precision
if spec.measurement:
    self._requires_cap = key
```

> 0.3.x 里每条规格是个 6 元组，解包成
> `name, device_class, state_class, unit, category, _prec`。
> 那个 `_prec` **解包出来就再也没用过**（下划线前缀已经暗示了），
> 于是小数位数全由 HA 根据 `device_class` 自己猜，表里写的值是装饰。
> 改成 `SensorSpec` 数据类之后每个字段都有名字，
> 少用一个就是显眼的死字段，不会再悄悄烂掉。

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
def _closed_pct(self) -> int | None:
    raw = self._device.state.get("position")
    try:
        return max(0, min(100, int(raw)))
    except (TypeError, ValueError):
        pass
    cover = str(self._device.state.get("cover", "")).upper()
    if cover == "CLOSED":
        return 100
    if cover == "OPEN":
        return 0
    return None

@property
def current_cover_position(self) -> int | None:
    closed = self._closed_pct()
    return None if closed is None else 100 - closed

async def async_set_cover_position(self, **kwargs) -> None:
    open_pct = max(0, min(100, int(kwargs.get(ATTR_POSITION, 0))))
    await self._hub.async_publish_set(self._device, {"position": 100 - open_pct})
```

对照表（`is_closed` 那一列见 [§8.2](#82-is_closed-由设备说了算)）：

| 物理状态 | 固件 `position` | 固件 `cover` | HA `current_position` | `is_closed` |
|---|---:|---|---:|:-:|
| 全开 | 0 | `OPEN` | 100 | ✗ |
| 开 70% | 30 | `OPEN` | 70 | ✗ |
| 半开 | 50 | `OPEN` | 50 | ✗ |
| 关 97% | 97 | `CLOSED` | 3 | **✓** |
| 全关 | 100 | `CLOSED` | 0 | ✓ |

> 注意 HA 里这个属性叫 **`current_position`**，不是
> `current_cover_position`（后者是 Python 里的属性名）。
> 写模板时用 `state_attr('cover.x_cover', 'current_position')`。

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

### 8.2 `is_closed` 由设备说了算

```python
@property
def is_closed(self) -> bool | None:
    cover = str(self._device.state.get("cover", "")).upper()
    if cover in ("OPEN", "CLOSED"):
        return cover == "CLOSED"
    position = self.current_cover_position
    return None if position is None else position == 0
```

**优先信设备自己的判断。** 固件在
`en2m_model.c` 里用 `v >= 95 ? "CLOSED" : "OPEN"` 推出 `cover` 字段，
容忍电机的机械误差——关到 97% 对一个卷帘来说就是关好了。
集成不该在这上面再加一个自己的阈值去和设备争。

只有在设备没报 `cover` 字段时才退回看位置，这时用 HA 的标准语义
（`current_position == 0`）。

> 0.3.x 里这里写的是 `self._closed_pct() >= 95`，等于把固件的阈值
> 抄了一份到 HA。抄对了没问题，但两处就有两处要维护，
> 而且**和它自己报出去的 `current_position` 会矛盾**：
> 位置 3% 时 HA 前端的滑条不在底，图标却显示已关闭。

### 8.3 `position` 缺失时的回退

`_closed_pct()` 读不到 `position` 就看 `cover` 字段
（`"OPEN"` / `"CLOSED"`），映射成 0 / 100。

这让**不支持位置反馈的窗帘**（只报开/关）也能工作，
只是 HA 的位置滑条会在 0 和 100 之间跳。

两个字段都没有时返回 `None`，HA 显示 unknown。

> 0.3.x 的回退默认值是 `"OPEN"` → 0（全开），
> 所以一个既没 `position` 也没 `cover` 的设备会**显示成"全开"**——
> 一个它从没说过的状态。现在这种情况老实显示 unknown。

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
    _requires_cap = "lock"

    @property
    def is_locked(self) -> bool | None:
        raw = self._device.state.get("lock")
        if raw is None:
            return None
        return str(raw).upper() == "LOCKED"

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
#: Exactly the modes `en2m_hvac_mode_str()` can emit and `en2m_hvac_mode_parse()`
#: can accept. Advertising more would let HA send a mode the device silently
#: turns into "off".
_MODE_MAP = {
    "off": HVACMode.OFF,
    "auto": HVACMode.AUTO,
    "cool": HVACMode.COOL,
    "heat": HVACMode.HEAT,
    "fan_only": HVACMode.FAN_ONLY,
}
_MODE_REV = {v: k for k, v in _MODE_MAP.items()}

#: What `turn_on` means for a thermostat that has no separate power switch.
_DEFAULT_ON_MODE = HVACMode.AUTO

class EspNowClimate(EspNowEntity, ClimateEntity):
    _attr_name = "Thermostat"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = list(_MODE_MAP.values())
    _attr_min_temp = 5
    _attr_max_temp = 35
    _attr_target_temperature_step = 0.5
    _requires_cap = "climate"
```

| HA 属性 | 读哪个字段 | 备注 |
|---|---|---|
| `hvac_mode` | `hvac_mode` | 通过 `_MODE_MAP` 映射，**认不出来的返回 `None`**（见 [§10.1](#101-模式表和固件一一对应)） |
| `current_temperature` | `current_temperature`，**回退到 `temperature`** | `float()`，失败返回 `None` |
| `target_temperature` | `target_temperature` | 同上 |

| HA 操作 | payload |
|---|---|
| `set_hvac_mode(M)` | `{"hvac_mode":<_MODE_REV[M]>}`，M 不在表里则**什么都不发** |
| `set_temperature(temperature=T)` | `{"target_temperature":<float>}` |
| `turn_on()` | `{"hvac_mode":"auto"}` |
| `turn_off()` | `{"hvac_mode":"off"}` |

`TURN_ON` / `TURN_OFF` 是给 `climate.turn_on` / `climate.turn_off` 这两个
service 用的。温控器没有独立的电源开关，所以"开"被定义成切到 `auto`
（`_DEFAULT_ON_MODE`）——让设备自己决定是制冷还是制热。

### 10.1 模式表和固件一一对应

`_MODE_MAP` 只有 off / auto / cool / heat / fan_only，
这**不是漏了**，而是刻意和固件的
`en2m_hvac_mode_str()` / `en2m_hvac_mode_parse()` 对齐
（device 仓库 `components/espnow_device/src/en2m_types.c`）。

Matter 的 `SystemMode` 确实还有 `dry(8)`、`precooling(5)`、
`emergency_heat(6)`、`sleep(9)`，但 `en2m` 固件不发这些字符串、
也不认这些字符串。如果在 `_attr_hvac_modes` 里多列几个，
结果是 HA 里能选 "Dry"、发出去 `{"hvac_mode":"dry"}`、
固件 parse 失败当成 `off` 处理——**UI 上能选但按下去把设备关了**。
所以下行方向这里宁缺毋滥：`_MODE_REV.get()` 返回 `None` 时
`async_set_hvac_mode` 直接 return，一个字节都不发。

上行方向则相反，要防的是"猜错"：

```python
@property
def hvac_mode(self) -> HVACMode | None:
    raw = self._device.state.get("hvac_mode")
    if raw is None:
        return None
    # An unrecognised mode used to be reported as "off", which is an active
    # lie about a running thermostat. Returning None shows it as unknown.
    return _MODE_MAP.get(str(raw).lower())
```

> **0.3.x 里**这行是 `_MODE_MAP.get(str(raw).lower(), HVACMode.OFF)`。
> 一个报了 `"dry"` 的定制固件会让 HA 显示"关闭"，
> 而房间里的机器正在除湿。你据此写的
> "温控器关了就关窗"自动化会在最糟的时候触发。
>
> 现在返回 `None`，HA 显示 `unknown`。这在自动化里很好区分：
> `is_state('climate.x', 'off')` 对 `unknown` 不成立，
> 而 `unknown` 本身就是"固件报了个我不认识的模式"的信号。

要真正支持更多模式，两侧都得改：固件的 `en2m_hvac_mode_str()` 加输出、
`_MODE_MAP` 加条目。只改一侧都会出上面那两种问题之一。

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

`ClimateEntityFeature` 里的 `FAN_MODE` / `PRESET_MODE` / `SWING_MODE`
没有实现——固件的 Thermostat cluster 也没有对应的可写属性。
`TURN_ON` / `TURN_OFF` 有，见 [§10](#10-climate) 的操作表。

---

## 11. Event（按钮）

按钮是唯一一个**没有状态**的能力。等 HA 听说这件事的时候，
按下和松开都已经结束了。把它做成 sensor 的话，
值会永远停在最后一次按的那个数上——所以它走 HA 的 `event` 平台，
记录的是"什么时候发生了哪一种按法"，而不是"现在是什么值"。

```python
EVENT_TYPES = ["press", "double_press", "long_press", "release"]

class EspNowButtonEvent(EspNowEntity, EventEntity):
    _attr_name = "Button"
    _attr_event_types = EVENT_TYPES
    _requires_cap = "button"

    def __init__(self, hub: EspNowHub, device: EspNowDevice) -> None:
        super().__init__(hub, device, "button")
        self._last = self._fingerprint()

    def _fingerprint(self) -> tuple:
        state = self._device.state
        return (state.get("button"), state.get("button_action"))
```

| | |
|---|---|
| 实体 ID | `event.<设备名>_button` |
| unique_id | `<MAC>_button` |
| 创建条件 | `"button" in caps` |
| 读哪些字段 | `button`（必须）、`button_action`（可选） |
| 事件类型 | `press`、`double_press`、`long_press`、`release` |
| 命令 | **没有**，这是纯上行实体 |

> **0.3.x 里 `button` cap 走到 Hub 就没人接了。**
> Hub 会老老实实把它放进 `dev.caps`、在 `espnow2mqtt_mac` 属性里
> 也能看到，但八个平台没有一个认领它，
> 所以一个只声明 `["button"]` 的设备在 HA 里**只有三个诊断实体**，
> 按键按了完全没有反应。当时的解法只能是在 MQTT 层面写自动化
> （`platform: mqtt` + `topic: espnow2mqtt/<slug>/state`），
> 绕开整个集成。

### 11.1 为什么必须把 `button` 报成计数器

`<slug>/state` 是 **retained** 的，而且固件每次上报都会把全部字段重发一遍
（见 [state-flow.md §10](state-flow.md#10-ha-重启后会发生什么)）。
这带来一个硬性限制：

**一次按键只能被识别成 `button` 值的"变化"。**

连续两条一模一样的值，和"同一条消息被重发"在 MQTT 层面
是完全无法区分的。所以设备侧的正确做法是把 `button` 当成
**一个每次按键都自增的计数器**。`en2m` 固件的 Switch cluster
（`EN2M_DEVICE_TYPE_GENERIC_SWITCH`）就是这么做的，
`en2m_report_button()` 自己维护那个计数器，例程见
[device 仓库 examples/scene_switch](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/examples.md#scene_switch)。

上报长这样：

```json
{"button": 7, "button_action": "double_press"}
```

下一次按就是 `{"button": 8, ...}`。指纹是
`(button, button_action)` 这个二元组，任一个变了就发事件。

| 固件这么报 | 结果 |
|---|---|
| `{"button": 1}`、`{"button": 2}`、`{"button": 3}` | 3 个 `press` 事件 ✅ |
| `{"button": "press"}` 连发三次 | **只有第 1 个**触发事件 ❌ |
| `{"button": 1, "button_action": "press"}` 然后 `{"button": 1, "button_action": "long_press"}` | 2 个事件（`press` + `long_press`）✅ |

另外 `current[0] is not None` 这个条件保证了：
HA 重启后 retained 的 `<slug>/state` 被重放时，
`__init__` 里已经把 `self._last` 设成了当时的指纹，
所以**不会凭一条 retained 消息伪造出一次按键**。

### 11.2 事件类型是归一化的

固件报什么 `button_action` 字符串都行，集成会折叠到四种之一：

```python
_ALIASES = {
    "single": "press", "single_press": "press", "click": "press",
    "pressed": "press", "short": "press", "short_press": "press",
    "double": "double_press", "double_click": "double_press",
    "hold": "long_press", "long": "long_press", "held": "long_press",
    "released": "release",
}

@staticmethod
def _event_type(raw: object) -> str:
    value = _ALIASES.get(str(raw).strip().lower(), str(raw).strip().lower())
    return value if value in EVENT_TYPES else "press"
```

认不出来的一律当 `press`。这里和 climate 的取舍**正好相反**——
按键是纯上行、没有副作用，"漏报一次按键"比"报错按法"更糟，
所以宁滥毋缺。

没有 `button_action` 时，`_event_type` 拿到的是 `button` 本身的值
（通常是个整数），也会落到 `press`。所以**只报计数器不报按法
的设备会得到一串 `press` 事件**，这是正确的降级。

### 11.3 事件的 `event_type` 和属性

`_trigger_event` 带了两个额外属性：

```python
self._trigger_event(
    self._event_type(...),
    {"value": current[0], "action": current[1]},
)
```

所以在自动化里能同时拿到归一化后的类型和固件的原话：

```yaml
trigger:
  - platform: state
    entity_id: event.kitchen_button_button
condition:
  - "{{ trigger.to_state.attributes.event_type == 'double_press' }}"
action:
  - service: system_log.write
    data:
      message: >
        counter={{ trigger.to_state.attributes.value }}
        raw={{ trigger.to_state.attributes.action }}
```

`value` 就是那个自增计数器，可以用来检测丢包
（相邻两次事件的 `value` 差了 3，说明中间漏了 2 次）。

---

## 12. Bridge 连通性实体

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

### 12.1 协调器的自述都挂在这个实体的属性上

`<base>/bridge/info` 是协调器的 hello 行（协议版本、信道、固件、MAC）。
HA 里没有别的地方能放这些信息，所以它们成了这个实体的
`extra_state_attributes`：

```python
@property
def extra_state_attributes(self) -> dict[str, Any]:
    info = self._hub.bridge_info
    attrs: dict[str, Any] = {"base_topic": self._hub.base}
    for key in ("mac", "fw", "channel", "version", "role", "stack"):
        if info.get(key) is not None:
            attrs[key] = info[key]
    attrs["devices"] = len(self._hub.devices)
    return attrs
```

| 属性 | 来源 | 意思 |
|---|---|---|
| `base_topic` | config entry | 这个 entry 用的 MQTT 前缀，多协调器时用来区分 |
| `mac` | `bridge/info` | 协调器自己的 MAC |
| `fw` | `bridge/info` | 协调器固件版本 |
| `channel` | `bridge/info` | ESP-NOW 工作信道 |
| `version` | `bridge/info` | USB 串行协议版本 |
| `role` | `bridge/info` | 通常是 `coordinator` |
| `stack` | `bridge/info` | 底层栈标识 |
| `devices` | Hub | 当前 `hub.devices` 的条数（含 `slug:` 占位） |

`bridge/info` 没到之前，只有 `base_topic` 和 `devices` 两个属性。

> **0.3.x 里 `bridge/info` 这个主题根本没被订阅。**
> `hub.bridge_info` 这个字典存在、初始化成 `{}`，然后再也没人写过它。
> 协调器辛辛苦苦发上来的信道和固件版本，在 HA 里一个字都看不到；
> 想知道协调器跑在哪个信道上，只能自己 `mosquitto_sub`。
> 现在 Hub 订阅了它，见
> [architecture.md §3.4](architecture.md#34-bridgeinfo协调器自述)。

### 12.2 固件版本是事后补写进注册表的

`sw_version` 属于 `DeviceInfo`，而 **`device_info` 只在实体第一次被添加时
读一次**。这个实体在 `async_setup_entry` 里就建好了，
比 retained 的 `bridge/info` 到达早得多——
所以光在 `device_info` 里填 `sw_version` 是不够的，
设备页上会永远是空的。

```python
@callback
def _on_bridge(self, entry_id: str) -> None:
    if entry_id != self._hub.entry.entry_id:
        return
    # This entity is created at setup, long before `bridge/info` arrives, so
    # the firmware version has to be written to the registry after the fact.
    info = self._hub.bridge_info
    async_sync_device_registry(
        self.hass,
        "bridge",
        sw_version=str(info["fw"]) if info.get("fw") else None,
    )
    self.async_write_ha_state()
```

`async_sync_device_registry` 在 `entity.py` 里，会比对再写，
没变化就不动注册表。普通设备实体的 `model` 走的是同一条路
（见 [architecture.md §10](architecture.md#10-设备注册表的层级)）。

### 12.3 这是判断整套系统死活的正确实体

`SIGNAL_BRIDGE_UPDATED` 只被这个实体订阅，
所以 `bridge_online` 变化时只有它会被直接通知。
但 Hub 在处理 `bridge/state` 时会**额外给每个设备补一发**
`SIGNAL_DEVICE_UPDATED`：

```python
@callback
def _on_bridge_state(self, msg: mqtt.ReceiveMessage) -> None:
    self.bridge_online = self._text(msg.payload).strip().lower() == "online"
    async_dispatcher_send(self.hass, SIGNAL_BRIDGE_UPDATED, self.entry.entry_id)
    # Device entities derive `available` from the bridge too, so they have to
    # be told as well; otherwise they keep showing a stale value until their
    # own state topic happens to fire.
    for mac in list(self.devices):
        async_dispatcher_send(
            self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac
        )
```

所以协调器掉线时，Bridge 实体变 `off`，
**所有设备实体同时变 `unavailable`**。

> **0.3.x 里没有那个 for 循环。** `available` 的公式
> （`bridge_online and device.online`）是对的，但没人在
> `bridge_online` 变化时叫设备实体重算，
> 而 `SIGNAL_DEVICE_UPDATED` 只在收到该设备的状态上报时才发——
> 协调器挂了就永远不会再有状态上报。
> 结果是**所有设备实体永久停在"可用"，显示着协调器死前的最后一个值**。
> 这是最坏的一种失效：面板上看一切正常。

即便如此，**写告警自动化还是应该监控
`binary_sensor.*_bridge` 从 `on` 变 `off`**，而不是某个设备实体变
unavailable——因为协调器一挂，几十个设备实体会同时变 unavailable，
逐个监控会推几十条通知。见
[usage.md §4](usage.md#4-推荐的自动化)。

---

## 13. 按设备类型看会出什么

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
| `scene_switch` | `["button"]` | `event.*_button`（[§11](#11-event按钮)） |
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
