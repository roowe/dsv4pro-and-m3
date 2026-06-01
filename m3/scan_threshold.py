#!/usr/bin/env python3
"""并发阈值扫描：跑 c=2,5,10,15 找出稳定性拐点。"""

import argparse
import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from load_test import load_config, run_model, summarize


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--concs", default="2,5,10,15", help="逗号分隔的并发档位")
    parser.add_argument("-n", "--n", type=int, default=30, help="每档每模型请求数")
    parser.add_argument("--model", help="只测指定模型（避免多模型互相干扰）")
    args = parser.parse_args()

    api_key, base_url, models = load_config()
    if args.model:
        if args.model not in models:
            raise SystemExit(f"模型 {args.model!r} 不在列表 {models} 中")
        models = [args.model]
    chat_url = f"{base_url}/chat/completions"
    concs = [int(x) for x in args.concs.split(",") if x.strip()]
    n = args.n
    prompt = "用一句话介绍你自己。"
    max_tokens = 64

    print(f"Scan: concs={concs}  n/model={n}  models={models}\n")

    async with httpx.AsyncClient() as client:
        rows = []
        for c in concs:
            for model in models:
                print(f"\n==> c={c}  model={model}", flush=True)
                results = await run_model(
                    client, chat_url, api_key, model, prompt, max_tokens, n, c
                )
                s = summarize(model, results)
                s["conc"] = c
                rows.append(s)

    print("\n" + "=" * 100)
    print("Threshold Scan")
    print("=" * 100)
    header = f"{'c':>3}  {'model':18s}  {'succ%':>6s}  {'avg/p50/p95/p99(s)':>22s}  errors"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['conc']:>3}  {r['model']:18s}  {r['succ%']:>6s}  "
            f"{r['avg/p50/p95/p99(s)']:>22s}  {r['errors']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
