# espnow2mqtt-ha 文档

这里是 **Home Assistant 自定义集成**的完整文档。它是整条链路的最后一段：
把 Bridge 发到 MQTT 上的 JSON 变成 HA 里的实体。

```
[ C3 设备 ] --ESP-NOW--> [ S3 协调器 ] --USB--> [ Bridge ] --MQTT--> [ HA 集成 ]
  device 仓库                 host 仓库             host 仓库          ↑ 本仓库
```

另外两个仓库：

- **[espnow2mqtt-host](https://github.com/SFNFIH/espnow2mqtt-host)** — S3 协调器固件 + Python Bridge + HA Add-on。
  它的 [`docs/mqtt.md`](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md)
  是**本集成读写的每一个主题的权威定义**，看本仓库文档前建议先扫一遍。
- **[espnow2mqtt-device](https://github.com/SFNFIH/espnow2mqtt-device)** — C3 设备固件和 `en2m` 组件。
  它的 [`docs/`](https://github.com/SFNFIH/espnow2mqtt-device/tree/main/docs)
  是整套系统里最厚的一份，解释每个字段在设备侧是怎么算出来的。

## 这个集成做什么、不做什么

| | |
|---|---|
| **做** | 订阅 6 个 MQTT 主题；在内存里维护设备表；按 `caps` 动态创建 8 种平台的实体；把 HA 的服务调用翻译成 `<slug>/set` 上的 JSON |
| **不做** | 不碰串口、不认识 ESP-NOW、不解析空口帧。**没有 Bridge 就什么都没有** |
| **不做** | 不用 MQTT Discovery。实体是集成自己建的，所以 Bridge 的 `--ha-discovery` 应该**保持关闭** |
| **不做** | 不写 YAML。设备自动出现（`iot_class: local_push`） |

## 按需求找文档

| 我想…… | 看这篇 |
|---|---|
| 装上并跑通 | [quickstart.md](quickstart.md) |
| 搞懂集成的分层、Hub、dispatcher 信号 | [architecture.md](architecture.md) |
| 搞懂一条 MQTT 消息怎么变成实体状态、实体怎么被创建 | [state-flow.md](state-flow.md) |
| 查 `caps` → 平台的映射、每个实体的字段和单位换算 | [entities.md](entities.md) |
| 查服务、自动化写法、模板取值 | [usage.md](usage.md) |
| 实体没出来 / 状态不更新 / 控制没反应 | [troubleshooting.md](troubleshooting.md) |
| 知道 0.3.x 有哪些毛病、0.4.0 改了什么 | 本页 [0.4.0 修掉的实现缺口](#040-修掉的实现缺口) |
| 查 MQTT 主题和 payload | [host 仓库 docs/mqtt.md](https://github.com/SFNFIH/espnow2mqtt-host/blob/main/docs/mqtt.md) |
| 配对说明和控制 JSON 速查 | [homeassistant.md](homeassistant.md) |

## 建议的阅读路线

**只想用**

1. [quickstart.md](quickstart.md)
2. [entities.md](entities.md) 查你的设备会出哪些实体
3. [usage.md](usage.md) 抄自动化
4. 卡住了查 [troubleshooting.md](troubleshooting.md)

**想改代码**

1. [architecture.md](architecture.md) 先看清 Hub / Entity / Platform 三层怎么分工
2. [state-flow.md](state-flow.md) 再看数据怎么流、实体怎么被动态创建
3. [entities.md](entities.md) 最后看每个平台的具体映射

## 0.4.0 修掉的实现缺口

这一版之前，这份文档里有一张"已知的实现缺口"表，列的是读代码时发现的、
**当时确实存在**的行为。它们现在全部修掉了，每条都有回归测试钉住
（`tests/test_gaps.py`，一个测试对应一条）。留在这里是因为
如果你在用 0.3.x，这些就是你会遇到的症状：

| 0.3.x 的行为 | 0.4.0 起 | 详见 |
|---|---|---|
| 实体只增不减：设备丢掉一个 `cap` 后旧实体永远留着 | cap 消失时实体自删，并从实体注册表里清掉；cap 回来还能重建 | [state-flow.md](state-flow.md#6-实体能增也能减) |
| `bridge_info` 从未被填充，拿不到协调器的信道/固件版本 | 订阅 `bridge/info`，落到 Bridge 实体属性和协调器设备的 `sw_version` | [architecture.md](architecture.md#34-bridgeinfo协调器自述) |
| `slug:` 占位设备永远不和真设备合并，可能出两套实体 | 拿到真 MAC 后把占位设备连状态一起并进去，并删掉占位的设备条目 | [state-flow.md](state-flow.md#33-slug-占位设备) |
| 命令失败没有反馈，`<slug>/set` 是纯单向 | Bridge 发布 `<slug>/command_result`，集成订阅并抛 `espnow2mqtt_command_failed` 事件 | [usage.md](usage.md#7-命令的成败反馈) |
| caps 映射表里 `fan_mode`/`target_temperature`/`current_temperature` 三行取不到，只报这些键的风扇和温控器认不出来 | 键列表和映射合成一张表，不可能再漂移 | [state-flow.md](state-flow.md#341-_cap_from_state_key级-3-的全部内容) |
| 灯的 color mode 在 `__init__` 里冻住，第一帧没带 `color_temp` 就永远是纯调光灯 | 每次读都重新判定 | [entities.md](entities.md#32-色温mired--kelvin) |
| sensor 的精度字段解包后丢掉了 | 落到 `suggested_display_precision` | [entities.md](entities.md#5-sensor) |
| Bridge 掉线时设备实体不重算可用性 | Hub 在 `bridge/state` 变化时扇出给所有设备 | [architecture.md](architecture.md#6-dispatcher-信号) |
| `button` cap 走到 Hub 就没人接，不产生任何实体 | 新增 `event` 平台 | [entities.md](entities.md#11-event按钮) |
| `ATTR_MAC`/`CAPS`/`HOP`/`VIA`/`NODE_ROLE` 是没人引用的常量 | 成为每个实体的属性，模板里能取到拓扑 | [usage.md](usage.md#5-在模板里取值) |
| `unique_id` 是域名，永远只能有一个条目 | 改成按主题前缀区分，第二个协调器可以加进来 | [usage.md](usage.md#11-多个协调器) |

顺带修掉的还有三处：实体基类里指针刷新的条件写反了；温控器收到不认识的模式会
上报成 `off`（在撒谎，现在报 unknown）；`mqtt_not_ready` 这个 abort 分支
不可达（`dependencies` 里写了 `mqtt` 会让 HA 一开流程就把它加载上，
所以那个判断永远成立）。

## 版本

| | |
|---|---|
| 集成版本 | `manifest.json` 里 `0.4.0` |
| HA 最低版本 | `hacs.json` 里 `2024.11.0`（`OptionsFlow.config_entry`、`ClimateEntityFeature.TURN_ON`、`event` 平台都要这个版本以上） |
| 依赖 | `mqtt` 集成（`dependencies`），**没有** Python 包依赖（`requirements: []`） |
| `iot_class` | `local_push` |
| 域名 | `espnow2mqtt` |
| 测试 | `pip install -r requirements_test.txt && pytest`（跑真实 HA core，35 个测试） |
