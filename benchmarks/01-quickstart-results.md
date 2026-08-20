# 01 - Measure: latency baseline

Model `Gemma 4 E2B` · host `Linux-x86_64` · llama.cpp `b10488`
Settings: `threads=10` `ngl=0` `ctx=2048`
`max_tokens=64` · warm-up discarded
Completed requests: `UD-Q4_K_XL` 10/10 · `UD-Q2_K_XL` 10/10

| Quantization | Size (GB) | Load (ms) | TTFT P50/P95 (ms) | TPOT P50/P95 (ms) | E2E P50/P95/P99 (ms) | Decode (tok/s) |
|:--|--:|--:|--:|--:|--:|--:|
| UD-Q4_K_XL | 2.97 | 5112 | 969 / 1619 | 175.3 / 190.4 | 11784 / 13303 / 13303 | 5.7 |
| UD-Q2_K_XL | 2.24 | 8140 | 1428 / 1713 | 169.9 / 189.4 | 12309 / 13262 / 13262 | 5.9 |

- **TTFT** = prefill. Short prompts keep it small; long-context RAG is where it explodes.
- **TPOT** = per-output-token decode cost, bounded by memory bandwidth. `decode tok/s = 1000 / TPOT_p50`.
- `UD-Q2_K_XL` decodes **1.04x faster** than `UD-Q4_K_XL` here, for 0.73 GB less on disk.

## Your observation

**Verdict: 2-bit is not worth it on this machine.** It saves 0.73 GB on disk (2.24 vs
2.97 GB, -25%) and returns essentially nothing in speed.

| | UD-Q4_K_XL | UD-Q2_K_XL | change |
|:--|--:|--:|--:|
| Decode | 5.7 tok/s | 5.9 tok/s | **1.04x faster** |
| TTFT P50 | 969 ms | 1428 ms | **1.47x slower** |
| On disk | 2.97 GB | 2.24 GB | 0.75x |

If decode were purely memory-bandwidth-bound, 25% fewer bytes should have bought roughly
25% more tokens/s. It bought 4%. And prefill went the *wrong* way by 47%.

The reason is that this run is `ngl=0` -- pure CPU. On CPU every quantized weight has to
be unpacked to float before it enters the GEMM, and Q2_K's unpack costs more ALU per
weight than Q4_K's. Both are two-level K-quants (an fp16 super-block scale times a small
quantized per-sub-block scale), but Q2_K splits its 256-weight super-block into **16
sub-blocks of 16 weights** where Q4_K uses **8 sub-blocks of 32**. Q2_K therefore does
twice as many scale lookups and multiplies per weight decoded, on every weight, every
token. On this i5-1335U there is no spare vector throughput to hide that behind, so the
dequantization cost eats the bandwidth saving almost exactly. Prefill is where it shows
worst, because prefill is compute-bound to begin with -- hence TTFT got *worse*.

Two further things keep the size ratio from being the 2:1 the names imply: "UD" (Unsloth
Dynamic) deliberately holds sensitive tensors at higher precision, and the embedding and
output tensors take a large share of a 4.6B-parameter file at these bit widths. The real
ratio is 0.75x, not 0.5x -- so even the bandwidth argument had less to work with than
the label suggests.

**Quality check.** I put an identical prompt to both ("Explain in 3 sentences why decode
is memory-bandwidth-bound but prefill is compute-bound", `seed=42`, `max_tokens=160`),
serving 4-bit on :8080 and 2-bit on :8090 as the guide suggests. Both answers came back
coherent, correctly structured as three sentences, and factually right; I could not
separate them on quality. So the case against 2-bit here is *not* that it degraded the
answer -- it is that it bought no speed to pay for the risk.

*(I am deliberately not quoting latencies from that side-by-side: the 2-bit server had
just loaded, so its weights were cold in the page cache while the 4-bit server had been
serving for minutes. The table above, from `make bench`, is the fair comparison -- it
loads each model in isolation and discards a warm-up request.)*

**When I would still take 2-bit:** only if 2.97 GB did not fit. This laptop has 15.3 GB,
so I am not in that regime. On an 8 GB machine also running a browser, 0.73 GB can be
the difference between resident and swapping, and swapping would cost far more than the
4% I measured.
