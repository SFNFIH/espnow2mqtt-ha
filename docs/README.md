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
| **做** | 订阅 4 个 MQTT 主题；在内存里维护设备表；按 `caps` 动态创建 7 种平台的实体；把 HA 的服务调用翻译成 `<slug>/set` 上的 JSON |
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

## 已知的实现缺口

这几条是读代码时发现的**真实问题**，都在对应文档里详细写了原因和影响，
不是"未来计划"而是"当前行为"：

| 缺口 | 影响 | 详见 |
|---|---|---|
| 实体只增不减 | 设备丢掉一个 `cap` 后旧实体永远留着 | [state-flow.md](state-flow.md#6-实体只增不减) |
| `bridge_info` 从未被填充 | 集成拿不到协调器的信道/固件版本 | [architecture.md](architecture.md#34-没有订阅-bridgeinfo) |
| `slug:` 占位设备 | 极端顺序下可能产生一套重复实体 | [state-flow.md](state-flow.md#33-slug-占位设备) |
| 命令失败没有反馈 | `<slug>/set` 是单向的，HA 不知道命令是否成功 | [usage.md](usage.md#7-命令是单向的) |

## 版本

| | |
|---|---|
| 集成版本 | `manifest.json` 里 `0.3.0` |
| HA 最低版本 | `hacs.json` 里 `2024.1.0` |
| 依赖 | `mqtt` 集成（`dependencies`），**没有** Python 包依赖（`requirements: []`） |
| `iot_class` | `local_push` |
| 域名 | `espnow2mqtt` |
