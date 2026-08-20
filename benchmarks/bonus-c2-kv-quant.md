# Bonus C2 — KV cache quantization (`--cache-type-k/v q8_0`)

Host `Linux-x86_64` · CPU `13th Gen Intel Core i5-1335U` · llama.cpp `b10488` ·
model `gemma-4-E2B-it-UD-Q4_K_XL.gguf` · `threads=10` · `ngl=0` · `--parallel 4`
Script: `bonus/c2-kv-cache-quant.py` · raw data: `bonus-c2-kv-quant.json`

The deck's "FP8 KV cache" idea, checked on CPU. Model held fixed; two things varied —
the total context budget (which sets KV cache size) and the KV cache dtype. Measured
the thing that is actually scarce on a 15 GB laptop: **resident memory**, plus decode
and prefill throughput, plus answer quality on an identical prompt (`seed=42`).

| ctx (total) | ctx/slot | KV dtype | RSS (MB) | Δ vs f16 | decode (tok/s) | prefill (tok/s) |
|:--|--:|:--|--:|--:|--:|--:|
| 2048 | 512 | f16 (default) | 3954.3 | — | 6.19 | 34.04 |
| 2048 | 512 | q8_0 | 3943.2 | **−11.1** | 5.02 | 31.98 |
| 8192 | 2048 | f16 (default) | 4022.3 | — | 5.22 | 22.27 |
| 8192 | 2048 | q8_0 | 3983.3 | **−39.0** | 5.11 | 22.51 |

## What it bought

**Almost nothing, and the reason is the model, not the flag.**

q8_0 is half the bytes of f16, so the saving equals half the KV cache. Working backwards
from the deltas: the f16 KV cache is roughly **22 MB at ctx=2048** and **78 MB at
ctx=8192**. Cross-checked against the context sweep — going 2048 → 8192 (4×, +6144
tokens) grew RSS by only 68 MB, about 11 KB/token — the two estimates agree.

Against ~3.0 GB of weights, the KV cache is **0.6% of RSS at the lab default and 1.9% at
4× the context**. Quantizing it saved 0.3% and 1.0% of process memory respectively.

Gemma 4 E2B is the reason the number is this small. `bonus/README.md` notes it shares KV
across 20 of its 35 layers, and most layers use sliding-window attention, so KV does not
grow per-layer the way a vanilla transformer's does. On a model with full per-layer
global attention the same flag would matter far more — this result is about *this*
architecture, not about `--cache-type-k` being useless.

## What it cost

Decode came out 6.19 / 5.02 / 5.22 / 5.11 tok/s across the four runs. The obvious read is
"q8_0 costs 19% at ctx=2048", but at ctx=8192 the same comparison is 5.22 vs 5.11 — 2%.
**One 19% gap and one 2% gap from the same change is noise, not a trend**, and the
ctx=2048/f16 point (6.19) is the outlier against the other three which cluster at ~5.1.
Single-request measurements on a machine that swings this much do not support a claim
either way. I am reporting the ambiguity rather than picking the run that tells a
cleaner story; settling it would need repeated runs per config, which is what
`llama-bench -r` does and what this ad-hoc script does not.

Prefill shows no consistent penalty either (34.04 → 31.98 at 2048, 22.27 → 22.51 at 8192
— opposite directions).

## Quality

Identical prompt, `seed=42`, `max_tokens=80`, both dtypes at both context sizes. All four
answers were correct and near-identical; f16 and q8_0 differ only in wording
("particularly in long sequence processing" vs "in large language models"), and the two
context sizes produced byte-identical output within each dtype. **No quality regression
was observable at this scale** — but a 1-prompt check cannot detect the failure mode that
matters for KV quantization, which is degradation late in a long context. That would need
the 10-prompt eval the challenge suggests, run at ctx near full.

## Verdict

**I would not enable this on this machine.** It targets 0.6–1.9% of resident memory on a
model whose KV cache is already small by design, with a possible decode cost I could not
rule out. The memory pressure on this laptop comes from the 3 GB of weights — the lever
that actually moves is quantization of the *weights*, and
`benchmarks/01-quickstart-results.md` shows even that trade (UD-Q2_K_XL) failing on speed
here.

**Where it would earn its place:** a model with full global attention at every layer, a
long context, and many concurrent slots — all three multiply the KV cache. Serving
`--parallel 32` at `--ctx-size 131072` on a dense-KV model is the regime the deck is
describing, and it is a different machine from this one.
