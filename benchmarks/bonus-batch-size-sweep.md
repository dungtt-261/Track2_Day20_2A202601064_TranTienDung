# Bonus - Batch-size sweep (chunked prefill)

Host `Linux-x86_64` · llama.cpp `b10488` ·
`threads=10` `ngl=0` · metric `pp512`

| -b (logical) | -ub (micro) | pp512 (tok/s) | vs best |
|:--|--:|--:|--:|
| 128 | 128 | 19.5 | 94% |
| 256 | 256 | 20.3 | 98% |
| 512 | 256 | 20.8 | 100% |
| 512 | 512 | 20.4 | 98% |
| 1024 | 512 | 19.4 | 93% |
| 2048 | 512 | 20.8 | 100% |

Best: `-b 2048 -ub 512` at 20.8 tok/s
(1.07x the slowest point tested).

This sweep only measures the throughput half of the trade. The cost it hides is
TTFT for queued requests: a larger micro-batch holds the device longer per step,
so anything waiting behind it waits longer. To see both halves, re-run
`make load-50` with your best and worst settings via
`.venv/bin/python labs/02-serve/serve.py -- -b N -ub M` and compare P95.

## Your finding

**Which setting would I run in production? The default. This sweep found nothing, and
the nothing is the result.**

The whole grid spans 19.4 to 20.8 tok/s -- a 1.07x spread across a 16x range of logical
batch size. Before trusting even that, I measured the run-to-run noise: an independent
`llama-bench -p 512 -r 1 -b 512 -ub 512` on the same machine minutes earlier returned
**21.17 tok/s**, where this sweep recorded **20.4** for the identical configuration. That
is a 3.6% gap between two runs of the *same* setting, against a 7% spread across *all*
settings. The ordering inside the table is not stable either: `-ub 512` appears three
times, at 20.4, 19.4 and 20.8. **The sweep is measuring noise with a batch-size label on
it.**

**Why chunked prefill does not help here, and why that is the interesting part.**
Raising `-ub` from 128 to 512 means each micro-batch step reads the model weights once
and does 4x as many tokens' worth of GEMM with them. If prefill were bound by streaming
weights out of memory, amortising those reads 4x should have shown up plainly. It moved
the number by 4%. So the weights are *not* the binding constraint during prefill on this
box -- **the arithmetic is**. Prefill is compute-bound, exactly as the deck says, and a
knob that only improves memory reuse has nothing to work on.

That is the clean mirror image of what my base track found for decode.
`benchmarks/01-tuning-tg128.md` shows decode gaining only 1.44x from 5x the threads --
adding compute to a bandwidth-bound problem. Here I add memory reuse to a compute-bound
problem and get 1.07x. Same lesson from both directions: on this laptop the two phases
have opposite bottlenecks, and a knob is only worth turning if it targets the right one.

**What I would need to measure before being sure the default does not hurt P95 on a
contended server.** Throughput per prefill is only half the trade. A larger `-ub` holds
the CPU inside one prefill step for longer, and llama.cpp cannot interleave a decode step
for another slot until that micro-batch finishes. So a big `-ub` buys prefill efficiency
by adding head-of-line blocking for everyone already decoding. The experiment that
settles it is the one the report suggests: re-run `make load-50` at `-ub 128` and at
`-ub 512` and compare **P95, not RPS**, while watching `n_busy_slots_per_decode` for
whether the batching width collapses during long prefills.

I did not run that experiment, and I am flagging it rather than implying the default is
safe under load. What my base track already established is that this server saturates at
`--parallel 4` with 46 requests deferred, so it is *exactly* the regime where head-of-line
blocking would show up. On a box where prefill runs at 21 tok/s, a single 260-token
`long-rag` prompt occupies the machine for ~12 s; the micro-batch size determines how
finely that 12 s can be interleaved with everyone else's decode. That, not the 7% in the
table above, is where `-ub` actually matters here.
