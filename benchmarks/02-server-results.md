# 02 - Serve: load test + saturation reading

Host `Linux-x86_64` · llama.cpp `b10488` ·
`--parallel 4` · `ctx=2048` · `threads=5` ·
`ngl=0`

| Users | Reqs | RPS | P50 (ms) | P95 (ms) | P99 (ms) | Eff. concurrency | Failures |
|:--|--:|--:|--:|--:|--:|--:|--:|
| 10 | 8 | 0.16 | 47000 | 51000 | 51000 | 5.0 | 0.0% |
| 50 | 4 | 0.21 | 19000 | 19000 | 19000 | 3.7 | 0.0% |

*Effective concurrency = RPS x average latency (Little's Law) -- how many requests were
really in flight, regardless of how many users locust simulated. It counts queued requests
too, so the occupancy/slot ratio can legitimately exceed 1.0; it is occupancy, not
utilisation. For true slot utilisation use the server's own gauges (`make metrics`).*

## What these two runs say

| Going from 10 to 50 users | |
|:--|--:|
| Offered load | 5x |
| Throughput actually delivered | **1.34x** (27% of linear) |
| P95 latency | **0.37x** |
| Effective concurrency at 50 users | 3.7 vs `--parallel 4` slots (occupancy/slot ratio 0.93) |

**Saturated.** Throughput delivered only 1.34x for 5x the offered load, and effective concurrency (3.7) is at or above all 4 decode slots. Saturation sets in somewhere at or below 50 users; the load you added beyond that point became queue time rather than throughput.

P95 grew no faster than throughput (0.37x vs 1.34x), so this server still has headroom at 50 users.

> **Small sample.** Only 4 requests completed in the
> shorter run, so these percentiles are indicative rather than solid. Note also that
> locust averages only *completed* requests: when the run ends with requests still
> queued, effective concurrency is an **under**-estimate. Trust the throughput-scaling
> row over the concurrency row here, and run longer (`-t 3m`) if you want firmer numbers.

## Your reading

**The server saturates at 4 concurrent requests -- exactly `--parallel` -- and it is
already past that at 10 users, let alone 50.** The number that convinced me is not in
the table above: it is `requests_deferred = 46`, sampled by `make metrics` while the
50-user run was in flight. 50 offered, 4 slots, 46 waiting. Slot occupancy
(`n_busy_slots_per_decode`) peaked at 3.67 of 4 = 92%, so the engine was neither idle
nor under-batching. There was simply nowhere to put request number five.

**The P95 row above is misleading and must not be read as headroom.** The generated
analysis says "P95 grew no faster than throughput (0.37x), so this server still has
headroom" -- P95 apparently *improved* from 51 s at 10 users to 19 s at 50. That is
survivorship bias, not headroom. Locust records only requests that **completed** inside
the 60 s window. The load profile mixes a `short` task (48 output tokens, weight 4) with
a `long-rag` task (260-token prompt, 96 output tokens, weight 1). At 10 users one
`long-rag` finished, at 50.5 s, and entered the sample. At 50 users **none did** -- all
4 completions were `short`. The 50-user percentile is computed over a sample that
saturation itself filtered down to the cheapest task type. The requests that would have
set a true P95 were still queued when the clock ran out, so they were never counted.

That is also why I distrust the effective-concurrency column (5.0 at 10 users vs 3.7 at
50). Little's Law here is `RPS x average latency over completed requests`; when a run
ends with 46 requests still queued, both inputs are computed over the survivors and the
result is an under-estimate. The report's own footnote says as much. The server-side
gauges do not have this problem because they count what the scheduler actually held, so
I read saturation off `/metrics`, not off locust.

**Sample size, stated plainly:** 8 completed requests at 10 users, 4 at 50. Percentiles
over 4 points are indicative at best, and locust's approximated percentiles are bucketed
to the nearest second on top of that. What I would defend from this run is the
throughput direction (0.16 -> 0.21 RPS for 5x the offered load = 27% of linear) and the
server gauges. The latency percentiles I would not.

**What I would change first to raise goodput@SLO: not a server knob -- the work per
request.** Ranked for this box:

1. **Cap `max_tokens` and set the SLO per task type.** At ~11 tok/s decode, a 48-token
   answer costs ~4.4 s of pure decode before any queueing at all, and the 96-token
   `long-rag` costs ~9 s. No scheduler setting repairs a workload whose *service time*
   already exceeds a sane SLO; this is the only change that moves the arrival-rate to
   service-rate ratio in the right direction.
2. **`-t 5` on the server** -- applied here, worth 1.11x on the controlled `llama-bench`
   sweep (see `01-tuning-tg128.md`).
3. **Raising `--parallel` is the knob I would *not* touch first**, which is the
   counter-intuitive part, and on this build it would actively break. Two reasons.
   First, more slots on a CPU-only box add no compute; they split the same memory
   bandwidth across more concurrent decodes, so throughput stays roughly flat while
   every individual request slows down -- P95 gets worse and goodput@SLO *falls* even
   as "requests in flight" looks healthier. That is the throughput-vs-goodput trap:
   past saturation you buy throughput by spending latency, and if the SLO is a P95
   target you are spending exactly the thing being measured. Second, concretely:
   `--ctx-size 2048` is the total, divided across slots, so 4 slots get 512 tokens
   each. The `long-rag` prompt tokenizes to **260 tokens** (I checked via the server's
   `/tokenize`) plus 96 generated = 356 of 512. Going to `--parallel 8` would cut each
   slot to 256 tokens and the `long-rag` requests would fail outright rather than
   merely queue. Raising slots without raising context is not a tuning change, it is an
   outage.
