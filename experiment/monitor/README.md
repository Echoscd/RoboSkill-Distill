# Kinex Run Monitor

面向 Kinex + RoboTwin 实验的只读实时监控面板。它不会发送机械臂控制命令，数据来自：

- RoboEnv `head_camera` 的只读 RGB-D 采集（默认 2 Hz，只展示 RGB）；
- Kinex JSON 事件流 `events.jsonl`；
- 工作区 `.kinex/devices` 与 `.kinex/tools`；
- RoboEnv `run.json` 和终止证据。

界面包含模拟器实时画面、设备拓扑、完整工具箱、已使用工具、每次调用的输入/输出、耗时、错误、token、API 成本和 native success 状态。模拟器停止后会自动退回 trace 中最后一张图，因此同一页面也能用于离线复盘。

## 启动

在开发机上：

```bash
cd /LargeModelDev/users/chendong.song/kinex
./experiment/monitor/start.sh
```

默认监听 `127.0.0.1:8765`，并自动跟随 `env/iterations` 中最新的 `events.jsonl` 和 RoboEnv `run.json`。

在本机建立 SSH 隧道：

```powershell
ssh -N -L 8765:127.0.0.1:8765 drobotic
```

然后打开 <http://127.0.0.1:8765>。

## 绑定指定实验

```bash
./experiment/monitor/start.sh \
  --trace /path/to/attempt/events.jsonl \
  --roboenv-run /path/to/roboenv/session/run.json
```

常用选项：

- `--camera head_camera`
- `--camera-hz 2`（限制范围 0.2–5 Hz）
- `--port 8765`
- `--host 127.0.0.1`

也可以通过 `KINEX_REPO`、`KINEX_WORKSPACE`、`KINEX_ITERATIONS_ROOT` 覆盖默认目录。

## 和新测试一起使用

先启动 monitor，再启动 RoboTwin 与 Kinex 测试即可。自动发现器会在
`experiment/` 下出现新的 `events.jsonl` 或 `run.json` 后切换到最新实验，
无需重启页面。要查看旧的 `env/iterations` 记录，可通过 `--trace` 和
`--roboenv-run` 显式指定。

页面右上角的“导出快照”会下载当前聚合状态；原始完整记录仍保存在实验目录的 `events.jsonl` / `session.jsonl` 中。

## 安全边界

- monitor 只调用 RoboEnv 的 `devices.call/read`；
- 不调用 `write`、`stop`、`load` 或 `unload`；
- 不修改 Kinex trace、设备 profile 或工具定义；
- 建议只监听回环地址，通过 SSH tunnel 访问。
