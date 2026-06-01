#!/usr/bin/env python3
"""LLM API 并发稳定性压测（OpenAI Chat 格式）。"""

import argparse
import asyncio
import re
import statistics
import time
from collections import Counter
from pathlib import Path

import httpx
from dotenv import dotenv_values


def load_config():
    env_path = Path(__file__).parent / ".env"
    raw = dotenv_values(env_path)

    api_key = raw.get("CUSTOM_API_KEY")
    base_url = (raw.get("CUSTOM_BASE_URL") or "").rstrip("/")
    if not api_key or not base_url:
        raise SystemExit(".env 中缺少 CUSTOM_API_KEY 或 CUSTOM_BASE_URL")

    # 模型列表优先读 MODELS=，否则从 .env 的注释行 `# name: {}` 兜底解析
    models = []
    explicit = raw.get("MODELS")
    if explicit:
        models = [m.strip() for m in explicit.split(",") if m.strip()]
    elif env_path.exists():
        for line in env_path.read_text().splitlines():
            m = re.match(r"^\s*#\s*([\w.\-]+)\s*:\s*\{\s*\}\s*$", line)
            if m:
                models.append(m.group(1))

    if not models:
        raise SystemExit(
            "未找到模型列表。请在 .env 中添加 MODELS=model1,model2 或 `# model: {}` 注释行"
        )

    return api_key, base_url, models


async def one_request(client, chat_url, api_key, model, prompt, max_tokens):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    start = time.perf_counter()
    try:
        resp = await client.post(chat_url, json=payload, headers=headers, timeout=60)
        elapsed = time.perf_counter() - start
        if resp.status_code == 200:
            data = resp.json()
            usage = data.get("usage") or {}
            return {
                "ok": True,
                "elapsed": elapsed,
                "status": 200,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
        return {
            "ok": False,
            "elapsed": elapsed,
            "status": resp.status_code,
            "error": resp.text[:160],
        }
    except Exception as e:
        return {
            "ok": False,
            "elapsed": time.perf_counter() - start,
            "status": 0,
            "error": f"{type(e).__name__}: {str(e)[:140]}",
        }


async def run_model(client, chat_url, api_key, model, prompt, max_tokens, total, concurrency):
    sem = asyncio.Semaphore(concurrency)
    results = []
    step = max(1, total // 10)
    lock = asyncio.Lock()

    async def task():
        async with sem:
            r = await one_request(client, chat_url, api_key, model, prompt, max_tokens)
        async with lock:
            results.append(r)
            done = len(results)
            if done % step == 0 or done == total:
                ok = sum(1 for x in results if x["ok"])
                print(f"  [{model}] {done}/{total}  ok={ok}", flush=True)

    await asyncio.gather(*[task() for _ in range(total)])
    return results


def percentile(data, p):
    if not data:
        return 0.0
    s = sorted(data)
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] if f == c else s[f] + (s[c] - s[f]) * (k - f)


def summarize(model, results):
    total = len(results)
    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]

    if ok:
        lat = [r["elapsed"] for r in ok]
        avg = statistics.mean(lat)
        p50, p95, p99 = percentile(lat, 50), percentile(lat, 95), percentile(lat, 99)
        lat_str = f"{avg:.2f}/{p50:.2f}/{p95:.2f}/{p99:.2f}"
    else:
        lat_str = "-/-/-/-"

    err_counter = Counter(r["status"] for r in fail)
    if err_counter:
        sample_err = ""
        for r in fail:
            if r.get("error"):
                sample_err = r["error"]
                break
        err_str = ", ".join(f"{k}:{v}" for k, v in sorted(err_counter.items()))
        if sample_err:
            err_str += f"  e.g. {sample_err[:80]}"
    else:
        err_str = "-"

    return {
        "model": model,
        "total": total,
        "ok": len(ok),
        "fail": len(fail),
        "succ%": f"{len(ok) / total * 100:.1f}" if total else "-",
        "avg/p50/p95/p99(s)": lat_str,
        "errors": err_str,
    }


def print_table(rows):
    headers = list(rows[0].keys())
    cols = [[str(r[h]) for r in rows] for h in headers]
    widths = [max(len(h), max(len(c) for c in col)) for h, col in zip(headers, cols)]

    def fmt(values):
        return " | ".join(v.ljust(w) for v, w in zip(values, widths))

    print(fmt(headers))
    print("-+-".join("-" * w for w in widths))
    for r in rows:
        print(fmt([str(r[h]) for h in headers]))


async def main():
    parser = argparse.ArgumentParser(description="LLM API 并发稳定性压测")
    parser.add_argument("-c", "--concurrency", type=int, default=10, help="并发数（默认 10）")
    parser.add_argument("-n", "--total", type=int, default=50, help="每个模型请求数（默认 50）")
    parser.add_argument("--prompt", default="用一句话介绍你自己。", help="测试 prompt")
    parser.add_argument("--max-tokens", type=int, default=64, help="max_tokens（默认 64）")
    parser.add_argument("--chat-path", default="chat/completions", help="chat 端点路径，相对于 base_url")
    parser.add_argument("--model", help="只测指定模型（避免多模型互相干扰）")
    args = parser.parse_args()

    api_key, base_url, models = load_config()
    if args.model:
        if args.model not in models:
            raise SystemExit(f"模型 {args.model!r} 不在列表 {models} 中")
        models = [args.model]
    chat_url = f"{base_url}/{args.chat_path.lstrip('/')}"

    print(f"Base URL : {base_url}")
    print(f"Chat URL : {chat_url}")
    print(f"Models   : {models}")
    print(f"Concurrency / Model : {args.concurrency} / {args.total} reqs")
    print(f"Prompt   : {args.prompt!r}  max_tokens={args.max_tokens}\n")

    async with httpx.AsyncClient() as client:
        rows = []
        for model in models:
            print(f"==> {model}")
            results = await run_model(
                client, chat_url, api_key, model,
                args.prompt, args.max_tokens, args.total, args.concurrency,
            )
            rows.append(summarize(model, results))
            print()

        print("=" * 80)
        print("Summary")
        print("=" * 80)
        print_table(rows)


if __name__ == "__main__":
    asyncio.run(main())
