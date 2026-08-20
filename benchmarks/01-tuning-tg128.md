# 01 - Tune: thread-count sweep

Model `gemma-4-E2B-it-UD-Q4_K_XL.gguf` · host `Linux-x86_64` · llama.cpp `b10488`
CPU: **10 physical · 12 logical** cores · `ngl=0` · metric `tg128`

| threads (-t) | tg128 (tok/s) | vs best |
|:--|--:|--:|
| 1 | 5.2 | 70% |
| 5 | 7.5 | 100% |
| 10 | 6.7 | 90% |
| 12 | 6.4 | 85% |
| 24 | 5.2 | 70% |

**Best**: `-t 5` at 7.5 tok/s
**Slowest tested**: `-t 24` at 5.2 tok/s (1.43x spread)
**Against the physical-core default** (`-t 10`, 6.7 tok/s): 1.11x

Use this in your run:

```bash
LAB_N_THREADS=5 make bench
```

## Your explanation

**The knee is at `-t 5`, which is half my physical core count -- not at it.** The
expected shape (climb to physical cores, then flatten) does not hold on this CPU, and
the reason is the CPU itself.

`hardware.json` reports "10 physical - 12 logical", which reads like a uniform 10-core
part. It is not. From `/sys/devices/system/cpu/`:

| CPUs | Max freq | SMT siblings | What it is |
|:--|--:|:--|:--|
| cpu0-cpu3 | 4.6 GHz | (0-1), (2-3) | 2 P-cores, 2 threads each |
| cpu4-cpu11 | 3.4 GHz | none | 8 E-cores, 1 thread each |

The i5-1335U is 2 performance cores + 8 efficiency cores. The two are not
interchangeable: E-cores clock 1.35x lower *and* carry narrower vector units, so a
P-thread finishes an equal share of an AVX2 GEMM substantially faster than an E-thread.

That asymmetry is what breaks the curve. ggml splits every tensor op into **equal**
row-chunks, one per thread, and joins them at a barrier before the next op -- dozens of
barriers per decoded token. A barrier completes when the *slowest* thread completes.
Equal chunks on unequal cores means the P-cores spend most of every op parked at the
barrier waiting for E-cores. Each extra E-core thread past the knee adds a straggler,
not throughput.

Reading the rest of the curve with that in mind:

- **1 -> 5 threads: 5.2 -> 7.5 tok/s.** Only 1.44x for 5x the threads. Decode is
  bandwidth-bound, so most of that parallelism was never going to convert. The memory
  ceiling shows up long before the core count does.
- **5 -> 10: 7.5 -> 6.7 (-11%).** Threads 6-10 land on E-cores. The straggler cost
  exceeds the work they add.
- **10 -> 12: 6.7 -> 6.4 (-4%).** The last two threads are SMT siblings on the P-cores.
  Two hyperthreads on one core share one set of vector units, so each P-thread drops to
  roughly 60% speed and the *fast* threads become stragglers too. Hyperthreading hurts
  here for the usual dense-FP reason: there is no memory latency left to hide, the
  vector unit is already saturated.
- **12 -> 24: 6.4 -> 5.2.** 2x oversubscription. 24 runnable threads on 12 hardware
  threads means that at every barrier some participant has been descheduled and the
  rest wait for it to be rescheduled. Throughput falls back to exactly the
  single-thread number -- the clearest possible sign that the barrier, not the
  arithmetic, is now the bottleneck.

**Before/after: `-t 10` (the physical-core default the lab picks) 6.7 tok/s -> `-t 5`
7.5 tok/s = 1.11x, achieved by removing threads.** The spread across the sweep is 1.43x,
so choosing the thread count badly costs more than most other knobs in this lab would
buy back.

I checked it end to end rather than trusting `llama-bench` alone: `make bench` at the
default `-t 10` measured 5.7 tok/s decode, and `make smoke` against a server started
with `LAB_N_THREADS=5` reported **11.7-12.4 tok/s** across runs. Part of that much larger gap is the page
cache being warm by then, so the number I am claiming is the **1.11x from the controlled
sweep**, not the ~2x from comparing two differently-warmed runs.
