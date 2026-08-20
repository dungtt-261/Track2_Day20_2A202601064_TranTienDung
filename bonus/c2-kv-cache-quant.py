#!/usr/bin/env python3
"""Bonus C2 - KV cache quantization: what --cache-type-k/v q8_0 actually buys.

The deck's "FP8 KV cache" idea, checked on CPU. Holds the model fixed and varies
two things: the context budget (which sets KV cache size) and the KV cache dtype.
Measures the thing that is actually scarce on a 15 GB laptop -- resident memory --
plus decode speed and answer quality, so the trade is visible in all three.

    .venv/bin/python bonus/c2-kv-cache-quant.py
"""
from __future__ import annotations

import json, pathlib, subprocess, sys, time
import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))
import labkit  # noqa: E402

PORT = 8098
PROMPT = "In two sentences, what does PagedAttention solve?"
CONFIGS = [
    (2048, None),      # lab default
    (2048, "q8_0"),
    (8192, None),
    (8192, "q8_0"),
]


def rss_mb(pid: int) -> float:
    for line in pathlib.Path(f"/proc/{pid}/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return 0.0


def run(n_ctx: int, cache_type: str | None) -> dict:
    model = labkit.repo_root() / labkit.primary_model()
    extra = ["--ctx-size", str(n_ctx)]
    if cache_type:
        extra += ["--cache-type-k", cache_type, "--cache-type-v", cache_type]
    cmd = labkit.server_cmd(str(model), port=PORT, extra=extra)
    # server_cmd already injects --ctx-size from LAB_N_CTX; ours is appended later so it wins.
    log = open(labkit.repo_root() / "benchmarks" / ".c2-server.log", "w")
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
    try:
        labkit.wait_healthy(port=PORT, timeout=300)
        baseline = rss_mb(proc.pid)
        t0 = time.perf_counter()
        r = httpx.post(f"http://127.0.0.1:{PORT}/v1/chat/completions", timeout=600, json={
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": 80, "temperature": 0.7, "seed": 42,
        }).json()
        elapsed = time.perf_counter() - t0
        peak = rss_mb(proc.pid)
        tim = r.get("timings", {})
        return {
            "n_ctx": n_ctx,
            "cache_type": cache_type or "f16 (default)",
            "rss_after_load_mb": round(baseline, 1),
            "rss_after_request_mb": round(peak, 1),
            "decode_tok_s": round(tim.get("predicted_per_second", 0.0), 2),
            "prefill_tok_s": round(tim.get("prompt_per_second", 0.0), 2),
            "wall_s": round(elapsed, 2),
            "answer": r["choices"][0]["message"]["content"].strip(),
        }
    finally:
        proc.terminate()
        try: proc.wait(timeout=30)
        except subprocess.TimeoutExpired: proc.kill()
        log.close()
        time.sleep(2)


def main() -> int:
    labkit.banner("Bonus C2 - KV cache quantization")
    print(f"  model  : {pathlib.Path(labkit.primary_model()).name}")
    print(f"  threads: {labkit.threads()}   ngl: {labkit.n_gpu_layers()}\n")
    rows = []
    for n_ctx, ct in CONFIGS:
        label = ct or "f16"
        print(f"  ctx={n_ctx:<5} kv={label:<12} starting ...", flush=True)
        row = run(n_ctx, ct)
        rows.append(row)
        print(f"    RSS {row['rss_after_request_mb']:8.1f} MB   "
              f"decode {row['decode_tok_s']:5.2f} tok/s   "
              f"prefill {row['prefill_tok_s']:6.2f} tok/s")
    (labkit.repo_root() / "benchmarks" / "bonus-c2-kv-quant.json").write_text(
        json.dumps(rows, indent=2))
    print("\n==> Wrote benchmarks/bonus-c2-kv-quant.json")
    for r in rows:
        print(f"\n--- ctx={r['n_ctx']} kv={r['cache_type']} ---\n{r['answer'][:300]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
