# 03 - Integrate: RAG pipeline run

Host `Linux-x86_64` · llama.cpp `b10488` ·
retrieval backend: **keyword overlap** · 3 queries

| Query | Contexts retrieved | embed (ms) | retrieve (ms) | llm (ms) | total (ms) |
|:--|--:|--:|--:|--:|--:|
| Why is goodput more useful than raw throughp... | goodput, paged, radix | 0.0 | 0.1 | 7907.9 | 7908.0 |
| What problem does PagedAttention actually so... | paged, radix, disagg | 0.0 | 0.1 | 10438.8 | 10439.0 |
| When does splitting prefill and decode help?... | disagg, radix, batching | 0.0 | 0.1 | 9246.2 | 9246.4 |

Mean per stage (ms): embed **0.0** · retrieve **0.1** ·
llm **9197.6** · total **9197.8**
Dominant stage: **llm** (100% of total)

## Answers returned

**Why is goodput more useful than raw throughput?**

> Goodput@SLO counts only the requests per second that met the TTFT and TPOT targets. Throughput at saturation ignores SLOs.

**What problem does PagedAttention actually solve?**

> PagedAttention stores the KV cache in non-contiguous pages, removing the internal fragmentation that wasted most GPU memory.

**When does splitting prefill and decode help?**

> Splitting prefill and decode helps because prefill is compute-bound and decode is memory-bandwidth-bound.

## Which N16-N19 pieces are real

| Day | Piece | Real or stub | What is actually running |
|:--|:--|:--|:--|
| N16 Cloud/IaC | - | **stub** | localhost only. No cluster, no Compose stack, no IaC. `llama-server` is a plain local process on :8080. |
| N17 Data pipeline | - | **stub** | No DAG, no batch job. The corpus is the in-memory `TOY_DOCS` list shipped with `pipeline.py`. |
| N18 Lakehouse | - | **stub** | No Delta, no Iceberg, not even SQLite. Same in-memory list as N17. |
| N19 Vector + features | - | **stub** | No vector index and no embedding model. `pipeline.py` ran without `--embed-url`, so `embed()` returned nothing and `retrieve()` fell back to keyword overlap. That is why `embed` reads 0.0 ms -- it is not a fast embedder, it is an absent one. |
| N20 Serving | `llama-server` | **real** | Gemma 4 E2B UD-Q4_K_XL on llama.cpp `b10488`, `-t 5 -ngl 0 --ctx-size 2048 --parallel 4 --cont-batching`, reached over HTTP at `/v1/chat/completions`. |

Nothing upstream of serving is real in this run, and the `retrieval backend: keyword`
line at the top of this file is the honest label for it.

**Is the dominant stage what I expected? Yes -- but the margin is wider than I expected,
and the reason is about this laptop rather than about RAG.** llm is 9197.6 ms of a
9197.8 ms total: 100.0% to one decimal place. retrieve is 0.1 ms and embed is 0.0 ms, so
the retrieval side is not merely small, it is unmeasurable at this scale -- keyword
overlap across 5 documents held in a Python list.

The part worth reporting is *inside* the llm stage. From the per-query server timings,
the three queries spent **2964 / 6633 / 5529 ms in prefill** against **4884 / 3783 /
3690 ms in decode**. Prefill is roughly half the wall clock, and on queries 2 and 3 it
is the majority -- for prompts of only 113-149 tokens. That is not what the "decode
dominates" intuition predicts. It happens because `ngl=0` puts prefill's GEMMs on the
same 2 P-cores that decode is using, so the usual assumption -- prefill is cheap because
a GPU eats it in one batched pass -- does not transfer to a CPU-only box. Concretely,
prefill measured 13-46 tok/s here, which is the same order as decode, not orders above
it. Retrieved context is therefore *not* free on this machine: every extra chunk I put
in the prompt is paid for at prefill rates.

**If I had to halve this pipeline's latency I would attack the llm stage, and inside it
prefill first** -- there is nowhere else to go when one stage is 100% of the total.
Ranked:

1. **Prompt caching.** `SYSTEM_PROMPT` is a module-level constant in `pipeline.py`, so
   it is byte-identical across all three calls and the shared prefix is reusable; only
   the retrieved chunks and the question differ. Ordering the retrieved context stably
   and appending the volatile part last would let the server skip re-prefilling the
   prefix. On a workload where prefill is half the wall clock, that is the biggest lever
   available without changing hardware.
2. **Cut generated tokens.** At ~11 tok/s decode, the 23-30 tokens these answers used
   already cost 3.7-4.9 s. A hard `max_tokens` plus an explicit "answer in one sentence"
   is a real cut on the decode half, though these answers are already near the floor.
3. **Not a smaller quantization.** The obvious move would be dropping to UD-Q2_K_XL, and
   `benchmarks/01-quickstart-results.md` shows why it backfires here: 1.04x on decode
   and **1.47x worse on TTFT** -- which is precisely the half of this pipeline I most
   need to fix.
