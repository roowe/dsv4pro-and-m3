# dsv4pro-and-m3

## 动机

测两件事，顺手做一件：

1. **主目标**：自建 API 网关在并发下的承载力——具体说，是找到**成功率开始下跌**的那一档并发数（限流/过载拐点）。拿到这个水位线之后才能给业务侧一个安全的并发上限。
2. **副目标**：在同一组压测里把 **DeepSeek V4 Pro**（`dsv4pro/`）和 **MiniMax M3**（`m3/`）都跑一遍，顺手对比两个模型的编程能力。

需求本身很简单：写并发、跑起来、看错误数从哪里开始抬头、记下来。

## 目录

### `dsv4pro/` —— V4 Pro 快速验证

- `stress_test.py`：同步脚本，`OpenAI` SDK + `ThreadPoolExecutor`。
- CLI：`python stress_test.py <model> [并发数] [请求数]`，默认 c=5 / n=30。
- 只测一个模型，输出 min/avg/median/p95/p99 延迟 + QPS + 失败数。
- 适合先跑一发冒烟，确认 `CUSTOM_API_KEY` / `CUSTOM_BASE_URL` 是通的，再上更重的工具。

### `m3/` —— 通用异步压测

- `load_test.py`：异步，`httpx.AsyncClient` 复用连接 + `asyncio.Semaphore` 控并发。
  - 多模型支持：从 `.env` 的 `MODELS=...` 或 `# model: {}` 注释行读模型列表。
  - 输出每个模型的成功率、avg/p50/p95/p99 延迟、错误码分布。
  - `--model <name>` 可只测单个模型，避免多模型互相干扰。
- `scan_threshold.py`：多档并发扫描（`--concs 2,5,6,7,8,10,15`），复用 `load_test` 的 `run_model/summarize`。
- `pyproject.toml` + `uv.lock`：用 `uv` 管依赖（`httpx` + `python-dotenv`）。

## 用法

### dsv4pro

```bash
cd dsv4pro
echo "CUSTOM_API_KEY=..." > .env
echo "CUSTOM_BASE_URL=https://.../api" >> .env
python stress_test.py deepseek-v4-pro 5 30
```

### m3

```bash
cd m3
uv sync
cat > .env <<EOF
CUSTOM_API_KEY=...
CUSTOM_BASE_URL=https://.../api
MODELS=deepseek-v4-pro,MiniMax-M3
EOF

# 单档
uv run load_test.py -c 5 -n 50

# 多档扫描找拐点
uv run scan_threshold.py --concs 2,5,6,7,8,10,15 -n 30
```

## 怎么读结果

- **成功率** 是核心指标：100% → 90% 的那一档就是拐点，再高一档通常会雪崩。
- **错误体可能骗人**：网关过载时经常用统一兜底错误（如 `400 "Model not found"`）返回，**与"模型名写错"无关**。用串行基线（c=1）排除这个误判。
- **错误数按 status 分布**：看是 `ReadTimeout`（网络噪声）还是 `4xx/5xx`（限流）。两者要分开计数。
- **p99 延迟**比平均值更能反映排队；拐点前一档 p99 翻倍是常见信号。
- **两模型同档失败率接近** → 瓶颈在网关并发；差距明显 → 瓶颈在模型/上游。

## 拿到拐点之后

- 业务侧并发上限 = 拐点前一档（留 buffer）。
- 客户端超时 = 拐点档的 p99 + 余量。
- 拐点附近收到的 `4xx`：业务侧**退避重试**，不要把错误透传上去。
- 找网关运维确认真实限流策略（`Model not found` 这种兜底错误会盖住底层 RPS/worker-pool 限制）。
