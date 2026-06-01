#!/usr/bin/env python3
"""压力测试 —— 同步阻塞模式，并发完全可控。
用法:
  python stress_test.py <model> [并发数] [请求数]

示例:
  python stress_test.py deepseek-v4-pro          # 默认 concurrency=5, requests=30
  python stress_test.py deepseek-v4-flash 10 20  # 并发10, 共20请求
"""
import os
import sys
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

API_KEY = os.environ["CUSTOM_API_KEY"]
BASE_URL = os.environ["CUSTOM_BASE_URL"]

MODEL = sys.argv[1] if len(sys.argv) > 1 else "deepseek-v4-pro"
CONCURRENCY = int(sys.argv[2]) if len(sys.argv) > 2 else 5
REQUESTS = int(sys.argv[3]) if len(sys.argv) > 3 else 30

MESSAGE = [{"role": "user", "content": "Say 'hello' in exactly one word."}]


def request(i):
    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    t0 = time.monotonic()
    try:
        client.chat.completions.create(
            model=MODEL, messages=MESSAGE, max_tokens=10, temperature=0
        )
        return time.monotonic() - t0
    except Exception:
        return None


def main():
    print(f"目标: {BASE_URL}")
    print(f"模型: {MODEL}   并发: {CONCURRENCY}   总请求: {REQUESTS}")
    print(f"开始...", flush=True)

    t0 = time.monotonic()
    latencies = []
    errors = 0

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        futures = [pool.submit(request, i) for i in range(REQUESTS)]
        for f in as_completed(futures):
            r = f.result()
            if r is None:
                errors += 1
            else:
                latencies.append(r)

    elapsed = time.monotonic() - t0

    if latencies:
        latencies.sort()
        ok = len(latencies)
        print(f"\n  耗时: {elapsed:.1f}s    QPS: {ok/elapsed:.1f}    ok: {ok}   fail: {errors}")
        print(f"  min: {latencies[0]*1000:.0f}   avg: {statistics.mean(latencies)*1000:.0f}   median: {statistics.median(latencies)*1000:.0f}")
        p95 = latencies[int(ok * 0.95)]
        p99 = latencies[int(ok * 0.99)]
        print(f"  p95: {p95*1000:.0f}   p99: {p99*1000:.0f}   max: {latencies[-1]*1000:.0f}")
    else:
        print(f"\n  全部失败 ({errors})")


if __name__ == "__main__":
    main()