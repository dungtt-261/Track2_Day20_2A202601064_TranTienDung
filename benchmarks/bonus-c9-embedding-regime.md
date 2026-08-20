# Bonus C9 / B5 — Embedding serving as a different regime

Host `Linux-x86_64` · CPU `13th Gen Intel Core i5-1335U` · llama.cpp `b10488` ·
`llama-server --embedding --pooling mean` on :8081 · `ngl=0`
Commands: `make serve-embed` + `make embed-demo` · log: `26-embed-demo.log`

Embedding serving is structurally different from chat serving: **one forward pass per
text, no KV cache, no decode loop**. All the machinery the base track measured —
continuous batching, `--parallel` slots, `n_busy_slots_per_decode` — exists to overlap
*decode* steps, and there are no decode steps here. Throughput is supposed to come from
large **static** batches instead.

Backend reported `dim = 1536`, corpus of 8 documents.

## Retrieval works

Query: *"Does embedding serving use a KV cache and a decode loop like chat serving?"*

| Rank | Cosine | Document |
|--:|--:|:--|
| 1 | **0.843** | Embedding serving is prefill-bound: one forward pass, no KV cache, no decode loop. |
| 2 | 0.780 | RadixAttention reuses a shared prompt prefix across requests via a radix tree. |
| 3 | 0.747 | Speculative decoding drafts several tokens and verifies them in one forward pass. |

The correct document ranks first with a clear margin. Note this is a **chat** GGUF being
used as an embedder with mean pooling, not a trained embedding model — good enough to
demonstrate the regime, not good enough to deploy.

## The static-batch claim does not hold on this CPU

| Batch | Wall (ms) | Throughput (texts/s) | ms per text |
|--:|--:|--:|--:|
| 1 | 1463.0 | 0.7 | 1463 |
| 2 | 2246.3 | 0.9 | 1123 |
| 4 | 4541.4 | 0.9 | 1135 |
| 8 | 9471.4 | 0.8 | 1184 |
| 16 | 17633.7 | 0.9 | 1102 |

Batching 1 → 2 buys **1.30x**. Everything after that is flat: 2, 4, 8 and 16 all land
within noise of 1.1 s per text, and wall time scales almost exactly linearly with batch
size (2246 → 4541 → 9471 → 17634 is within 5% of perfect doubling each step).

**Why.** A static batch helps when the hardware has idle arithmetic at batch 1 — the
classic GPU case, where one text cannot fill the SMs and batching 32 costs barely more
than batching 1. This CPU has no such headroom. A single 1536-dim forward pass over a
4.65B-parameter model already saturates the vector units on 10 cores, so the second text
in the batch has to wait for arithmetic, not merely ride along on weights that were
already fetched. Batching amortizes **weight traffic**, and weight traffic is not what is
limiting prefill here.

## This is the same finding three times

| Experiment | Knob | Expected | Measured |
|:--|:--|--:|--:|
| B1 `compare-builds` | `-march=native` kernels | big win on weak CPU | **0.98x** |
| B2 `sweep-batch` | `-ub` 128 → 512 (4x weight reuse) | meaningful win | **1.07x** |
| C9 this table | static batch 1 → 16 | large win | **1.29x, then flat** |

Three independent knobs, all of which work by *reducing memory traffic per unit of work*,
all of which returned nothing. Read together with the base track — where decode gained
only 1.44x from 5x the threads (`01-tuning-tg128.md`) — the picture is consistent and
specific to this machine:

- **Prefill** (and embedding, which is all prefill) is **compute-bound**. Knobs that
  amortize memory reads have nothing to amortize; the ALUs are already the wall.
- **Decode** is **memory-bandwidth-bound**. Knobs that add compute have nothing to feed;
  the memory bus is the wall.

Every optimization in this bonus track targeted the wrong side of that split for its
phase. That is the finding, and it is more useful than any of the individual 1.0x numbers:
**on this laptop, know which phase you are optimizing before you pick the knob.**

## What would actually move the embedding number

Not batching. A smaller model — a purpose-built embedder like BGE-M3 or Qwen3-Embedding
is 0.1–0.6B rather than 4.65B, which cuts the per-text FLOPs by roughly an order of
magnitude and is also *better* at retrieval. On a compute-bound workload the only real
lever is doing less arithmetic, and using a 4.65B chat model to produce embeddings is the
most arithmetic-wasteful choice available. That is the honest recommendation this
experiment produces, and it is a model choice, not a serving-config choice.
