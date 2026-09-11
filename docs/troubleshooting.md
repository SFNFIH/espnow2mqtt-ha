# 排查手册（按症状）

**先做一件事：确认问题在哪一段。** 这个集成只是链路的最后一环，
大部分"HA 里不对"的问题根源在上游。

```
[ C3 设备 ] --ESP-NOW--> [ S3 协调器 ] --USB--> [ Bridge ] --MQTT--> [ HA 集成 ]
      ③                        ②                     ①                 ④ ← 本仓库
```

## 分诊：MQTT 上有东西吗？

在能跑 `mosquitto_sub` 的机器上（或者用 HA 的
**Settings → Devices & Services → MQTT → Configure → Listen to a topic**）：

```bash
mosquitto_sub -t 'espnow2mqtt/#' -v
```

| 结果 | 结论 | 去哪 |
|---|---|---|
| **完全没输出** | 上游没跑，或者前缀不是 `espnow2mqtt` | [host 仓库 troubleshooting](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/troubleshooting.md) |
| 只有 `bridge/state` 和 `bridge/info` | Bridge 在跑但没有设备 | [§2](#2-新设备不出现) |
| `bridge/devices` 是 `[]` | 设备没入网 | [host 仓库 §3](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/troubleshooting.md#3-设备不上线) |
| 有 `<slug>/state` 但 HA 里没实体 | **问题在集成侧** | [§1](#1-ha-里完全没有实体) / [§3](#3-实体少了) |
| 有 `<slug>/state` 且 HA 里有实体但值不对 | 问题在集成侧 | [§6](#6-值不对) |

**记住：MQTT 上有 = 上游全都是好的。** 集成读不到只可能是
base topic 不一致、MQTT 集成没配、或者集成本身的逻辑问题。

---

## 1. HA 里完全没有实体

### 1.1 base topic 不一致（最常见）

**Bridge 的 `--base-topic` 和集成里配的必须一字不差。**

先看 Bridge 实际用的前缀：

```bash
mosquitto_sub -t '#' -v | head -20
```

如果你看到 `myprefix/bridge/state online`，那 Bridge 用的是 `myprefix`。

再看集成里配的：**Settings → Devices & Services → ESP-NOW 2 MQTT → Configure**

改了之后集成会自动重载（`_async_update_listener` → `async_reload`），
不用重启 HA。

### 1.2 集成没装或没加载

```
Settings → Devices & Services → 应该看到 "ESP-NOW 2 MQTT" 卡片
```

没看到就是没加载。检查：

```bash
ls /config/custom_components/espnow2mqtt/
# 应该有 15 个 .py 文件 + manifest.json + services.yaml + translations/
```

装完必须**重启 HA**（不是"重新加载配置"——自定义集成的加载只在启动时发生）。

看日志里有没有加载失败：

**Settings → System → Logs**，搜 `espnow2mqtt`。

`manifest.json` 里 `"loggers": ["custom_components.espnow2mqtt"]`，
所以可以把它的日志级别单独拉高：

```yaml
# configuration.yaml
logger:
  default: warning
  logs:
    custom_components.espnow2mqtt: debug
```

> **注意：集成本身的日志非常少。** 只有
> `hub.async_start()` 里一条 `ESP-NOW hub listening on <base>/#`（INFO）。
> **所有 MQTT 处理失败都是静默返回的**（见
> [state-flow.md §3.1](state-flow.md#31-解析与过滤)）。
> 所以开 debug 也看不到"为什么这条消息被丢了"。
> 排查得靠 MQTT 那一侧。

### 1.3 添加集成时 abort

| 提示 | 原因 | 解决 |
|---|---|---|
| "MQTT integration is not set up. Add MQTT first." | HA 里没有**已加载**的 MQTT config entry | 先加 MQTT 集成（Settings → Devices & Services → Add → MQTT） |
| "ESP-NOW 2 MQTT is already configured" | **这个 base topic** 已经有 entry 了 | 想接第二个协调器就换一个前缀，见 [usage.md §11](usage.md#11-多个协调器) |

第二条只按 base topic 去重（`unique_id = f"{DOMAIN}:{base}"`），
所以**一个 HA 可以接多个协调器**，只要前缀不同。

> **0.3.x 里第二条是硬限制**（`_async_current_entries()` +
> `unique_id = DOMAIN`），一个 HA 只能接一个协调器。

第一条的判定是"存在一个 `state is ConfigEntryState.LOADED` 的 mqtt
config entry"。如果你明明装了 MQTT 却还是看到这个提示，
说明 MQTT 集成自己起不来（broker 连不上），
去 **Settings → Devices & Services → MQTT** 看它是不是红的。

> **0.3.x 里这个 abort 实际上永远不会触发。** 判定写的是
> `mqtt.DOMAIN not in hass.config.components`，
> 而 `manifest.json` 里声明了 `dependencies: ["mqtt"]`，
> HA 在启动 config flow 之前就把 mqtt 组件装载了——条件恒为假。
> 所以没配 MQTT 时你会看到正常的表单，填完保存，
> 然后集成静默地什么都收不到。原因见
> [architecture.md §8.5](architecture.md#85-一个协调器一个-entry)。

### 1.4 集成在但一个设备都没有

看 `binary_sensor.esp_now_coordinator_bridge`：

| 它的状态 | 含义 |
|---|---|
| **不存在** | 集成没起来 → [§1.2](#12-集成没装或没加载) |
| `off` | 收不到 `<base>/bridge/state` 上的 `online` → base topic 错，或 Bridge 没跑 |
| `on` | 集成和 Bridge 通了，问题在设备侧 → [§2](#2-新设备不出现) |

这个实体是**无条件创建**的（`binary_sensor.async_setup_entry` 里
`async_add_entities([EspNowBridgeBinary(hub)])`），所以它一定存在。
它不存在就说明 binary_sensor 平台压根没起来。

---

## 2. 新设备不出现

### 2.1 先确认 MQTT 上有没有

```bash
mosquitto_sub -t espnow2mqtt/bridge/devices -C 1 | python3 -m json.tool
mosquitto_sub -t 'espnow2mqtt/+/state' -v
```

| 结果 | 结论 |
|---|---|
| `bridge/devices` 是 `[]`，没有任何 `<slug>/state` | **设备没入网**，问题在上游 |
| 有设备但 HA 里没有 | 集成侧问题，往下看 |

设备没入网的排查在
[host 仓库 troubleshooting §3](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/troubleshooting.md#3-设备不上线)。
最常见的两个原因是**ESP-NOW 信道不匹配**和**配网窗口没开**。

### 2.2 配网窗口开了吗

```yaml
action: espnow2mqtt.permit_join
data:
  duration: 120
```

**这个服务没有任何反馈**——调完立刻返回，集成不知道有没有生效。
去 Bridge 的日志确认：

```
INFO espnow2mqtt: MQTT espnow2mqtt/bridge/request/permit_join => 120
INFO espnow2mqtt: coord: pairing_enabled
```

| 缺哪行 | 问题 |
|---|---|
| 第一行都没有 | **base topic 不一致**（集成发到了另一个前缀），或 Bridge 的 MQTT 订阅没建立 |
| 有第一行没第二行 | Bridge 到 S3 的串口链路有问题 |

服务不存在的话（Developer Tools 里找不到 `espnow2mqtt.permit_join`），
说明集成没加载成功。

### 2.3 只有诊断实体，没有功能实体

比如 HA 里出现了设备，但只有 `Mesh Hop` / `Node Role` / `RSSI` 三个。

**这说明 `bridge/devices` 到了，但 `<slug>/state` 没到（或者里面没有 caps）。**

因为诊断实体来自 `bridge/devices`，而**功能实体完全由 `caps` 决定，
`caps` 只从 `<slug>/state` 来**（见
[state-flow.md §3.4](state-flow.md#34-caps-推断三级-fall-through)）。

```bash
mosquitto_sub -t espnow2mqtt/<slug>/state -C 1 | python3 -m json.tool
```

| 结果 | 原因 | 解决 |
|---|---|---|
| 主题不存在 | 设备只发心跳不发状态 | 设备的上报模式可能是 `EN2M_REPORT_MANUAL`；等 30 秒；或 toggle 一下设备 |
| 有内容但没有 `caps` | 被 160 字节预算挤掉了，而且推断也没命中 | 见下 |
| 有 `caps` | 集成侧的问题，试重启 HA |

**没有 `caps` 时**，集成会退到从 payload 的 key 推断
（23 个 key + 一张映射表）。如果 payload 里只有集成不认识的 key，
就推不出任何 cap。注意映射表里有**三个死条目**
（`fan_mode`、`target_temperature`、`current_temperature` 不在
遍历的 key 元组里），所以一个只报 `{"fan_mode":"high"}` 的风扇
**推不出 `fan` cap**。见
[state-flow.md §3.4](state-flow.md#34-caps-推断三级-fall-through)。

### 2.4 等一个上报周期

叶子节点默认每 **30 秒**上报一次，常电节点 15 秒。

入网成功后固件会做一次快速上报（`on_link_change` 里
`next_report_ms = now + 200`），所以正常情况下几百毫秒内就有第一条状态。
**30 秒还没有就不正常了。**

### 2.5 重启 HA

`hub.devices` 是纯内存的，全靠 retained 消息重建。
重启后六个订阅建立、retained 消息涌入、平台起来时一次性看到全部设备。

**如果 MQTT 上确实有 `<slug>/state` 而 HA 里没实体，重启几乎一定能修好。**
重启后还是没有，那才是真的 bug。

---

## 3. 实体少了

### 3.1 按 caps 对一下应该有什么

先看设备实际报了什么 caps：

```bash
mosquitto_sub -t espnow2mqtt/<slug>/state -C 1 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print("caps =", d.get("caps")); print("keys =", sorted(d))'
```

然后查 [entities.md §1](entities.md#1-caps--平台映射) 的映射表。

### 3.2 按键设备只有诊断实体

按键走的是 HA 的 `event` 平台，实体叫 `event.<设备名>_button`。
如果它没出来：

1. **确认 caps 里有 `button`**（`button` 只能靠显式 caps 声明，
   不在 `_CAP_FROM_STATE_KEY` 里，所以光报 `button` 这个键**不会**
   被推断成能力）：

```bash
mosquitto_sub -t espnow2mqtt/<slug>/state -C 1 \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("caps"))'
```

2. 确认 `event` 平台起来了（HA 2023.8+ 才有这个平台，
   `hacs.json` 里要求 2024.11.0）

> **0.3.x 里 `button` cap 走到 Hub 就没人接了**，
> 按键设备在 HA 里只有三个诊断实体。
> 那时只能自己配 `platform: mqtt` 的自动化绕过集成。
> **如果你还留着那些 YAML，现在可以删了。**

### 3.2.1 按键实体有了，但按了不触发

`<slug>/state` 是 retained 的、而且每次上报重发全部字段，
所以**一次按键只能被识别成 `button` 值的变化**。
连发两个一样的值只会触发一次。

```bash
# 连按三次，看 button 的值有没有在变
mosquitto_sub -t espnow2mqtt/<slug>/state -v
```

`button` 一直是同一个值（比如恒等于 `"press"`）就是这个问题：
**固件应该把它报成一个每次按键自增的计数器**。
详见 [entities.md §11.1](entities.md#111-为什么必须把-button-报成计数器)。

### 3.3 灯没有色温滑条

先确认 MQTT 上到底有没有色温：

```bash
mosquitto_sub -t espnow2mqtt/<slug>/state -C 1 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("caps"), d.get("color_temp"), d.get("color_mode"))'
```

`caps` 里有 `color_temp`、或者 payload 里有 `color_temp` 键、
或者 `color_mode == "color_temp"`，三者任一成立就该有滑条。
三个都没有 ⇒ 固件根本没报色温，问题在设备侧
（[device 仓库 docs/reporting.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/reporting.md)）。

> **0.3.x 里这是个时序坑。** 色彩模式在**实体创建的那一刻**算一次就定死：
>
> ```python
> modes = {ColorMode.BRIGHTNESS}
> if "color_temp" in device.state or "color_temp" in device.caps:
>     modes = {ColorMode.COLOR_TEMP}
> ```
>
> 如果实体是在一条"被 160 字节预算挤掉了 `color_temp`"的上报上
> 建出来的，它会**永远**是纯调光灯，色温到了也不会长出滑条。
> 唯一的解法是重启 HA，赌重启时 retained 的那条 payload 里带色温。
>
> 现在 `supported_color_modes` 是个 property，每次读都重新判定，
> 色温字段到了滑条就出现。
> 详见 [entities.md §3.3](entities.md#33-色彩模式是每次读时判定的)。

### 3.4 温控器显示 `unknown`

`_MODE_MAP` 只认 5 种模式：`off` / `auto` / `cool` / `heat` / `fan_only`，
这是刻意和固件的 `en2m_hvac_mode_str()` 对齐的。
认不出来的值会让 `hvac_mode` 返回 `None`，HA 显示 `unknown`。

```bash
mosquitto_sub -t espnow2mqtt/<slug>/state -C 1 \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("hvac_mode"))'
```

不在那 5 个里（比如定制固件报了 `dry`）就是这个问题。
要支持得**两侧都改**：固件的 `en2m_hvac_mode_str()` 加输出、
`climate.py` 的 `_MODE_MAP` 加条目。
只改 `_MODE_MAP` 会让 HA 里能选一个固件 parse 不了的模式，
按下去等于把设备关了。详见
[entities.md §10.1](entities.md#101-模式表和固件一一对应)。

> **0.3.x 里这种情况显示的是"关闭"**（`_MODE_MAP.get(raw, HVACMode.OFF)`），
> 而设备实际在运行。这比显示 `unknown` 危险得多：
> `is_state('climate.x','off')` 会成立，
> 你的"温控器关了就关窗"自动化会在机器正在制冷的时候触发。

---

## 4. 控制没反应

### 4.1 集成有没有发出去

**Settings → Devices & Services → MQTT → Configure → Listen to a topic**，
监听 `espnow2mqtt/+/set`，然后在 HA 里点一下开关。

| 结果 | 结论 |
|---|---|
| 看到消息 | 集成侧正常，问题在下游 → [§4.2](#42-bridge-收到了吗) |
| 没看到 | 集成没发出去，或者发到了别的前缀 → [§1.1](#11-base-topic-不一致最常见) |

### 4.2 Bridge 收到了吗

Bridge 日志里必须有：

```
INFO espnow2mqtt: MQTT espnow2mqtt/living_room/set => {"switch":"ON"}
```

**没有这行**说明 Bridge 没订上这个主题，或者前缀不对。

### 4.3 `unknown device slug`

```
WARNING espnow2mqtt: unknown device slug old_name
```

**Bridge 的设备表里没有这个 slug。** 集成算出的 slug 和 Bridge 算出的
不一致，或者那个设备已经不在了。

两边的 slug 算法**逐字相同**：

```python
# hub.py（集成）                    # __main__.py（Bridge）
if name: return name.replace(" ","_").lower()
return mac.replace(":","").lower()
```

所以不一致只可能是 **`name` 不一致**。集成的 `name` 来自
`bridge/devices`，Bridge 的来自它的 `devices.json` + 设备上报——
理论上一样。

真实原因通常是：**你在 HA 里留着一个已经被移除/改过名的旧设备**。
集成的 `hub.devices` 是从 MQTT 重建的，但 HA 的实体注册表是持久化的，
所以老实体会一直在，点它就发到老 slug 上。

解决：在 HA 里删掉那个设备（**Settings → Devices → 齿轮 → 删除**），
并清掉 MQTT 上的孤儿主题：

```bash
mosquitto_pub -t espnow2mqtt/old_name/state -r -n
mosquitto_pub -t espnow2mqtt/old_name/availability -r -n
```

### 4.4 命令 ACK 了但状态没变

Bridge 日志里（开 `-v`）有 `ack: {... 'ok': True}`，但 HA 里状态不变。

**这说明设备收到了命令但拒绝了那个值。** 设备侧的写回调返回了非
`ESP_OK`，属性没有提交。

| 常见原因 | 例子 |
|---|---|
| 值超出范围 | 亮度给了 300 |
| 那个属性只读 | 往传感器的测量值写 |
| 设备上没有这个属性 | 往不支持色温的灯发 `color_temp` |
| 枚举值不支持 | 风扇的 `smart` 模式，固件可能没实现 |

要看拒绝原因，在设备上接 `idf.py monitor`。

集成侧的两个已知触发点：

- **风扇的 `smart` preset**：`PRESET_MODES` 里有它，但固件可能拒绝
  （[entities.md §7.3](entities.md#73-smart-模式固件可能不支持)）
- **灯的色温超出设备能力**：集成硬编码 2000–6500 K，
  设备会自己夹到能力范围内——这种情况下状态**会**变，只是不等于你设的值
  （[entities.md §3.2](entities.md#32-色温mired--kelvin)）

### 4.5 确认命令是不是真的失败了

**先看 `command_result`。** Bridge 会把协调器对每条命令的裁决
重新发布到这个主题：

```bash
mosquitto_sub -t 'espnow2mqtt/+/command_result' -v
```

然后在 HA 里点一下那个开关。

| 结果 | 结论 |
|---|---|
| `{"id":7,"ok":true,...}` | **命令送到了**。状态还不变 ⇒ 设备收到但拒绝了那个值 → [§4.4](#44-命令-ack-了但状态没变) |
| `{"id":7,"ok":false,"error":"timeout"}` | 发出去了，设备 1.6 秒内没确认（4 次重传后放弃）。设备断电 / 信号差 / 中继掉了 |
| `{"id":7,"ok":false,"error":"send_fail"}` | S3 根本没发出去。路由表里没这个 MAC，或 pending 表满 |
| **完全没输出** | 命令没到 Bridge → [§4.1](#41-集成有没有发出去)，或者 Bridge 版本太老（0.3.x 不发这个主题） |

失败的话集成还会在 HA 事件总线上 fire 一个
`espnow2mqtt_command_failed`。在
**Developer Tools → Events → Listen to events** 里填这个事件名，
然后点开关，能直接看到 `slug` / `error` / `payload`：

```json
{
  "entry_id": "01H...",
  "slug": "living_room",
  "mac": "AA:BB:CC:DD:EE:FF",
  "name": "Living Room",
  "id": 7,
  "error": "timeout",
  "payload": {"switch": "ON"}
}
```

`payload` 直接告诉你是哪个操作失败的。
配告警自动化见 [usage.md §7.2](usage.md#72-espnow2mqtt_command_failed-事件)。

> **0.3.x 里这一段只能去读 Bridge 的日志：**
>
> ```
> WARNING espnow2mqtt: command 7 to AA:BB:CC:DD:EE:FF failed: timeout
> ```
>
> 这些警告不进 MQTT，HA 完全不知道。唯一能在 HA 侧察觉的办法是
> "发命令 → 等 5 秒 → 检查状态"，而这对没有可读状态的命令
> （比如 `identify`）完全无效。

注意 `ok: true` 只意味着"协调器把帧送到了设备并收到链路层 ACK"，
不等于"设备照办了"。区别见
[usage.md §7.3](usage.md#73-事件不能完全替代状态校验)。

### 4.6 窗帘位置设错了方向

**固件的 `position` 和 HA 的是反的**：固件 0=开 / 100=关，
HA 0=关 / 100=开。

用 `cover.set_cover_position` 服务时集成会自动转换，**不用自己算**。

但如果你在用 `mqtt.publish` 手工发命令，**必须自己 `100 - x`**：

```yaml
# 想让窗帘开到 30%
payload: '{"position":70}'
```

详见 [entities.md §8.1](entities.md#81-位置的反转)。

### 4.7 HA 重启就自动开灯

**你往 `<slug>/set` 发过 retained 消息。** retained 的命令会在
Bridge 每次重连 MQTT 时重新投递。

```bash
mosquitto_sub -t 'espnow2mqtt/+/set' -v --retained-only     # 找出来
mosquitto_pub -t espnow2mqtt/living_room/set -r -n          # 清掉
```

集成自己发命令时 `retain=False`（`hub.async_publish_set` 里硬编码），
所以这一定是手工发的或者别的工具干的。

**规则：状态 retain，命令不 retain。**

---

## 5. 实体是灰的

### 5.1 可用性是两个条件的与

```python
@property
def available(self) -> bool:
    return self._hub.bridge_online and self._device.online
```

所以要分别查两个：

```bash
mosquitto_sub -t espnow2mqtt/bridge/state -C 1
mosquitto_sub -t espnow2mqtt/<slug>/availability -C 1
```

| `bridge/state` | `<slug>/availability` | 结论 |
|---|---|---|
| 不存在 / `offline` | 任意 | **Bridge 挂了**，或 base topic 错 |
| `online` | `offline` | 设备离线（协调器判的，90 秒无帧） |
| `online` | `online` | MQTT 上都是好的 → [§5.3](#53-两个都是-online-但实体还是灰的) |

### 5.2 全部实体都灰了

几乎一定是 `bridge_online` 是 `False`。它的初值就是 `False`，
只有收到 `<base>/bridge/state` 才会变。

看 `binary_sensor.esp_now_coordinator_bridge`：

| 它 | 含义 |
|---|---|
| `off` | 集成确实收不到 `bridge/state` → base topic 错 / Bridge 没跑 |
| `on` | `bridge_online` 是 True，那实体灰的原因是设备级的 |

### 5.3 两个都是 online 但实体还是灰的

**可能是 `SIGNAL_BRIDGE_UPDATED` 没触发设备实体刷新。**

`_on_bridge_state` 只发 `SIGNAL_BRIDGE_UPDATED`，而**这个信号只被
Bridge 那个连通性实体订阅**。设备实体的 `available` 要等下一条
`SIGNAL_DEVICE_UPDATED` 才重算。

所以场景是：Bridge 挂了一会儿（实体变灰）→ Bridge 回来了
（`bridge_online = True`）→ **但设备实体还是灰的**，
直到该设备下一次状态上报（最多 30 秒）。

**等 30 秒**。还是灰的就不是这个原因。

详见 [architecture.md §6](architecture.md#6-dispatcher-信号)。

### 5.4 Bridge 挂了但设备实体没变灰（反向问题）

这是同一个机制的另一面，而且**更危险**：

Bridge 挂掉后 `bridge/state` 通过 LWT 变成 `offline`
→ `bridge_online = False` → 逻辑上所有实体都该灰。
但设备实体要等下一条 `SIGNAL_DEVICE_UPDATED` 才重算，
而 Bridge 挂了就不会再有状态上报，
所以**设备实体可能一直停在"可用"状态直到 HA 重启**。

> **所以判断整套系统死活要看
> `binary_sensor.esp_now_coordinator_bridge`，
> 不要看某个设备实体是否变灰。**
>
> 自动化写法见 [usage.md §4.1](usage.md#41-监控-bridge-掉线)。

### 5.5 一个设备灰了

设备的离线判定来自协调器：`EN2M_OFFLINE_MS = 90000` ms 没收到任何帧。
设备心跳是 30 秒一次，所以允许连丢 2 次。

**判离线意味着 90 秒内一个字节都没上来**，这是很严重的丢包。
排查在
[host 仓库 troubleshooting §4](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/troubleshooting.md#4-设备时上时下)：
信号太弱（RSSI < -85）、供电不足、中继节点不稳。

先看 `sensor.<device>_rssi`。

---

## 6. 值不对

### 6.1 灯的亮度差 1

亮度经过**两次换算**：HA 0–255 → 固件 0–254 → HA 0–255。

```python
# 写
level = max(1, min(254, int(round(bri * 254 / 255))))
# 读
return max(0, min(255, int(round(level * 255 / 254)))) if level else 0
```

`round()` 在大部分值上是无损的，但个别值会偏 1。

**这是正常的，不是 bug。** 视觉上不可见。
但如果你的自动化里做了 `brightness == 200` 的精确比较，
会偶尔不成立——**改用范围比较**。

### 6.2 窗帘的开度是反的

见 [§4.6](#46-窗帘位置设错了方向) 和
[entities.md §8.1](entities.md#81-位置的反转)。

如果 HA 里显示的开度和实际相反，检查是不是有人手工发过
未转换的 `{"position":...}`。

### 6.3 窗帘显示"已关闭"但位置不是 0%

这是**正常的，而且是刻意的**。`is_closed` 先看设备自己报的 `cover`
字符串，只有它没报时才从位置推断：

```python
@property
def is_closed(self) -> bool | None:
    cover = str(self._device.state.get("cover", "")).upper()
    if cover in ("OPEN", "CLOSED"):
        return cover == "CLOSED"
    position = self.current_cover_position
    return None if position is None else position == 0
```

固件侧关闭判定有容差（电机停在 97% 也算关到底了），
所以会出现 `cover: "CLOSED"` 配 `position: 97` 的组合。
**以设备的裁决为准**是对的——它知道自己的限位开关在哪。

```bash
mosquitto_sub -t espnow2mqtt/<slug>/state -C 1 \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("cover"), d.get("position"))'
```

> **0.3.x 里集成自己拍了个阈值**（`_closed_pct() >= 95`），
> 完全不看设备报的 `cover` 字段。如果固件的容差和这个 95 不一样，
> 两边就会打架：设备说 `CLOSED`、HA 说"开着 6%"。
> 而且那个版本里 `is_closed` 的返回类型是 `bool`，
> **位置未知时会返回 `False`（"开着"）**，
> 一个还没上报过位置的窗帘在 HA 里看着是开的。
> 现在返回 `None`，显示 `unknown`。
> 详见 [entities.md §8.2](entities.md#82-is_closed-由设备说了算)。

### 6.4 温度/功率的数值明显不对

**固件已经换算过了**（÷100 / ÷100 / ÷10 / ÷1000 / ÷1000），
MQTT 上就是人类单位，集成只做 `float()`。

所以如果 HA 里显示 2345 °C，MQTT 上也一定是 2345——
说明**设备侧的 cluster 用错了**（比如往
`TemperatureMeasurement.MEASURED_VALUE` 写了 23.45 而不是 2345）。

```bash
mosquitto_sub -t espnow2mqtt/<slug>/state -C 1 | python3 -m json.tool
```

MQTT 上的值和 HA 里显示的一致 ⇒ 问题在设备固件，不在集成。
换算表见
[device 仓库 docs/reporting.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/reporting.md)。

### 6.5 温度小数位数不对

默认位数来自 `SENSOR_SPECS` 里那条规格的 `precision` 字段，
通过 `_attr_suggested_display_precision` 交给 HA。
这只是个**建议值**——你在 UI 里改过之后，实体注册表里的设置优先。

想改：**Settings → Entities → 该实体 → 齿轮 → 显示精度**。

> **0.3.x 里 `precision` 解包出来就扔了**：
>
> ```python
> name, device_class, state_class, unit, category, _prec = SENSOR_SPECS[key]
> ```
>
> 那个 `_prec` 再也没被提到过，小数位数完全由 HA 按 `device_class`
> 自己猜。功率会显示成 `123.4567 W` 这种。

详见 [entities.md §5.4](entities.md#54-规格是数据类不是元组)。

### 6.6 状态里有个早就不该存在的字段

`dev.state` 是**累积合并**的：

```python
merged = dict(dev.state)
merged.update(payload)
```

`dict.update()` 不删 key。所以**设备没法通过"不发某个字段"来表达
"这个字段消失了"**。一旦某个 key 出现过，它就留着直到 HA 重启。

这是刻意的，而且是必需的：160 字节的 payload 预算会让固件
在拥挤时分批上报字段（见
[state-flow.md §3.7](state-flow.md#37-合并与归一化)），
如果不累积，每次上报都会把上一批的字段清空。

代价是你改了固件、去掉一个属性之后，老的 key 会一直挂在那儿。
**解决：重启 HA**（内存表重建，只从 retained 的那一条恢复）。

> **注意这一条只管 `dev.state`，不管实体。**
> 如果 `caps` 里的某个能力消失了，对应的**实体会自删**，
> 见 [state-flow.md §6](state-flow.md#6-实体能增也能减)。
> `caps` 走的是替换而不是合并——显式上报的 `caps` 列表会整个换掉旧的。

### 6.7 同一个设备有两套实体

0.4.0 之后只剩一种可能：**Bridge 的 `--ha-discovery` 和本集成同时开着**，
表现是实体名带 `_2` 后缀。

> **0.3.x 里还有两种，都已经修掉了：**
>
> | 现象 | 0.3.x 的原因 |
> |---|---|
> | 同时有 `switch.x_switch` 和 `light.x_light` | Switch 实体在亮度字段到达之前就建好了，之后 caps 升级成 light 并把 `switch` 从 caps 里拿掉，但**实体只增不减**，Switch 永远留着（还停在最后一个值上） |
> | HA 里有两个设备，一个叫 slug 一个叫真名 | retained 的 `<slug>/state` 先到、`bridge/devices` 后到，产生了一个 `slug:` 占位设备，真 MAC 到了以后**两个并存** |
>
> 现在前者会自删（`EspNowSwitch._requires_cap = "switch"`），
> 后者会被合并（`_absorb_placeholder`）。
> 从 0.3.x 升上来的话，**这两种多余实体会在第一次收到状态上报时
> 自动消失**，不用手工删。
> 详见 [state-flow.md §6](state-flow.md#6-实体能增也能减) 和
> [state-flow.md §3.3](state-flow.md#33-slug-占位设备)。

Bridge 的 `--ha-discovery` 默认是关的，
但如果你之前开过，它发的 retained discovery config 主题还在：

```bash
mosquitto_sub -t 'homeassistant/+/espnow2mqtt_+/config' -v
```

有输出就说明 discovery 开着（或者留着老的 retained 消息）。

清理：

```bash
# 关掉 Bridge 的 --ha-discovery，然后逐个清 config 主题
mosquitto_pub -t homeassistant/switch/espnow2mqtt_living_room/config -r -n
mosquitto_pub -t homeassistant/sensor/espnow2mqtt_living_room_rssi/config -r -n
# ...
```

然后在 HA 里删掉那些 MQTT 集成创建的设备。

**别两个都开。** 选一个：简单设备用 discovery，完整支持用本集成。
本集成支持全部 16 种设备类型，discovery 只支持 7 种简单能力。

### 6.8 RSSI 不更新

**RSSI 只从 `bridge/devices` 来**（`<slug>/state` 里没有 RSSI）。

Bridge 每收到一条 USB 上的 `device` 行就重写这个主题，
即**每个设备每 30 秒一次**。所以 RSSI 的刷新周期是 30 秒。

设备离线时 RSSI 会**停在最后已知值**而不是变 unknown——
因为协调器的 `offline` 事件不带 `rssi` 字段。

```bash
mosquitto_sub -t espnow2mqtt/bridge/devices -C 1 | python3 -m json.tool
```

这里的值和 HA 里显示的一致就是正常的。

---

## 7. 性能问题

### 7.1 派发风暴

`bridge/devices` 的每个数组元素都会触发一次
`SIGNAL_DEVICE_UPDATED`：

```python
for item in lst:
    ...
    async_dispatcher_send(self.hass, SIGNAL_DEVICE_UPDATED, self.entry.entry_id, mac)
```

32 个设备 = 32 次派发 × (7 个平台的 `_discover` + 全部实体的
`_handle_update`)。Bridge 每 30 秒重写这个主题一次。

**单次开销极小**（`_discover` 因为 `uid in known` 立刻返回，
`_handle_update` 因为 MAC 不匹配立刻返回），
但如果你有几百个设备，这里会成为瓶颈。

症状：HA 的事件循环有周期性的小卡顿，
**Settings → System → Repairs** 里可能出现 "Detected blocking call"。

缓解：调长设备的上报间隔（减少 `device` 行的频率），
见 [device 仓库 docs/kconfig.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/kconfig.md)。

### 7.2 集成的日志量

集成**几乎不打日志**——只有启动时一条 INFO：

```
INFO custom_components.espnow2mqtt.hub: ESP-NOW hub listening on espnow2mqtt/#
```

所以它不会刷日志。这也意味着**排查只能靠 MQTT 那边**
（见本文开头的分诊）。

---

## 8. 从头重来

如果状态彻底乱了：

```
1. 在 HA 里：Settings → Devices & Services → espnow2mqtt → ⋮ → 删除
2. 清掉 MQTT 上所有 espnow2mqtt 的 retained 消息：
     mosquitto_sub -t 'espnow2mqtt/#' --retained-only -W 2 -F '%t' \
       | while read t; do mosquitto_pub -t "$t" -r -n; done
3. 如果开过 --ha-discovery，也清掉 homeassistant/ 下的 config 主题
4. 重启 Bridge（它会重发 bridge/state 和 bridge/info）
5. 在 HA 里重新添加集成
6. 等 30~60 秒让设备重新上报
```

第 2 步会让 HA 里所有实体短暂变 unknown，**但实体不会被删除**
（`unique_id` 还在注册表里），所以自动化不会断。

如果连设备都要重新配对，见
[usage.md §9](usage.md#9-彻底删掉一个设备) 和
[host 仓库 troubleshooting §9.4](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/troubleshooting.md#94-完全重来)。

---

## 9. 上游排查的入口

集成侧查完没问题，就往上游走：

| 层 | 文档 |
|---|---|
| Bridge（Python，MQTT ↔ USB） | [host 仓库 docs/bridge.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/bridge.md) |
| MQTT 主题的权威定义 | [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) |
| USB 上的 NDJSON 协议 | [host 仓库 docs/usb-protocol.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/usb-protocol.md) |
| S3 协调器固件 | [host 仓库 docs/coordinator.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/coordinator.md) |
| **按症状排查上游** | [host 仓库 docs/troubleshooting.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/troubleshooting.md) |
| C3 设备固件 / `en2m` 组件 | [device 仓库 docs/](https://github.com/SFNFIH/espnow2mqtt-device/tree/main/docs) |
| 字段是怎么算出来的 | [device 仓库 docs/reporting.md](https://github.com/SFNFIH/espnow2mqtt-device/blob/main/docs/reporting.md) |

---

## 相关文档

- [quickstart.md](quickstart.md) — 装的正确顺序和验证步骤
- [entities.md](entities.md) — 每个实体的字段、换算、边界条件
- [state-flow.md](state-flow.md) — 数据流，理解"为什么这条消息被丢了"
- [architecture.md](architecture.md) — 可用性和信号机制
- [usage.md](usage.md) — 自动化、模板、绕过集成的办法
