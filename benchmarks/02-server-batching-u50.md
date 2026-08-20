# 02 - Continuous batching under load (u50)

Host `Linux-x86_64` · `--parallel 4` · 30 samples over
60s at 2.0s intervals · raw CSV: `02-server-metrics-u50.csv`

| Gauge | Peak observed |
|:--|--:|
| `n_busy_slots_per_decode` (avg/decode) | 3.67 of 4 slots (92%) |
| `requests_processing` | 4 |
| `requests_deferred` | 46 |
| `kv_cache_usage_ratio` | n/a — not exported by llama.cpp `b10488` |
| `tokens_predicted_total` (final) | 837 |

Highest sampled value was **3.67 of 4** slots. Note this gauge is llama.cpp's *average* busy slots per decode step, so the number below is the highest average we sampled, not an instantaneous maximum batch width. A peak near 1 means
requests were served one at a time -- either the load was too light to overlap, or
they arrived too far apart. A peak approaching `--parallel` means the scheduler was
genuinely packing concurrent requests into shared decode steps.
`requests_deferred` went above zero: more requests arrived than there were slots, so some waited. That wait is the queue time in your P95.

## Your observation

**Peak batch width: 3.67 of 4 slots (92%), sampled while `make load-50` was running.**
`requests_processing` sat at 4 -- every slot occupied -- and `requests_deferred` peaked
at **46**, which is precisely the 50 offered users minus the 4 slots. Continuous
batching is demonstrably working: the scheduler packed nearly four concurrent requests
into shared decode steps instead of serializing them.

**Does it match the effective concurrency in `02-server-results.md`? Numerically almost
exactly -- 3.67 here against 3.7 there -- and that agreement is a coincidence I do not
trust.** The two measure different things and only happen to land in the same place:

- **3.67** is a server-side gauge: average slots busy per decode step. It is bounded
  above by `--parallel = 4` by construction, and it counts only work *inside* slots.
- **3.7** is Little's Law over locust's completed requests (`RPS x average latency`).
  It is meant to count queued requests too -- which means that with 46 requests
  deferred it should have come out far *above* 4, not below it.

It came out below 4 because locust averages only requests that finished inside the 60 s
window, and at 50 users only 4 short ones did. The 46 queued requests -- the entire
queueing signal -- never entered the average, so the client-side estimate collapsed back
onto roughly the slot count by accident. Two numbers agreeing for opposite reasons is
worse than two numbers disagreeing.

**I trust the gauges.** `requests_deferred = 46` is a direct count from the scheduler,
not an inference from a truncated sample. The practical reading: this server's
concurrency ceiling *is* `--parallel`, the 92% occupancy says that ceiling is genuinely
reached rather than left on the table, and everything past 4 in-flight requests is queue
time -- which shows up in the client's tail latency while never appearing in the
server's batch width.

Two limitations worth naming. `n_busy_slots_per_decode` is llama.cpp's *average* busy
slots per decode step, so 3.67 is the highest average I sampled, not an instantaneous
maximum; the instantaneous width almost certainly touched 4. And
`kv_cache_usage_ratio` is not exported by build `b10488`, so I could not watch how close
the per-slot context came to full -- with `--ctx-size 2048` split across 4 slots that is
512 tokens each, and the `long-rag` requests use 356 of them, so it would have been the
other gauge worth having.
