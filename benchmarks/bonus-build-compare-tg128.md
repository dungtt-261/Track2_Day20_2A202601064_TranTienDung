# Bonus B1 - Prebuilt vs source build

Host `Linux-x86_64` · CPU `13th Gen Intel(R) Core(TM) i5-1335U`
Vector extensions detected: AVX2
llama.cpp `b10488` both sides · `threads=10` ·
**both pinned to `ngl=0`** so this isolates the compiler ·
metric `tg128`, 3 repetitions

| Binary | Built for | tg128 (tok/s) | Relative |
|:--|--:|--:|--:|
| prebuilt release | runtime CPU dispatch | 6.8 | 1.00x |
| your source build | this CPU (`-DGGML_NATIVE=ON`) | 6.7 | 0.98x |

On this machine, **they are within 3% -- no meaningful difference**.

before: 6.8 tok/s (prebuilt release)
after:  6.7 tok/s (source build, -DGGML_NATIVE=ON)
speedup: 0.98x

Same source revision, same model, same backend, same `-ngl` -- the only difference
is what the compiler was allowed to assume about the CPU.
A gap this small usually means the prebuilt binary already dispatches to the right kernels at runtime (releases ship one libggml-cpu-*.so per microarchitecture and pick via CPUID), or that this workload is bandwidth-bound rather than instruction-bound. Both are real findings -- say which one you think it is.

## Your explanation

**The prebuilt won, by 2%, and the premise of this challenge is out of date.** The
bonus README says a weak CPU-only laptop should gain the most here because "the
prebuilt binary has to run on many machines so it only targets a common CPU baseline."
That was true of older llama.cpp releases. It is not true of `b10488`.

Evidence, straight off the two builds:

| | Prebuilt release | My source build |
|:--|:--|:--|
| CPU backends shipped | **14** (`libggml-cpu-{x64,sse42,sandybridge,ivybridge,haswell,alderlake,skylakex,icelake,cascadelake,cooperlake,cannonlake,sapphirerapids,zen4,piledriver}.so`) | **1** (`libggml-cpu.so`) |
| How the kernel is chosen | CPUID dispatch at load time | fixed at compile time by `-march=native` |
| What it loaded on this box | `libggml-cpu-alderlake.so` | n/a |
| Compiler | GNU 11.4.0 | GNU 16.1.1 |

The prebuilt is not a generic baseline binary. It is a **fat binary that picks a
microarchitecture-specific kernel at runtime**, and on this machine it picked the Alder
Lake one. The i5-1335U is Raptor Lake-P, which is the same ISA generation as Alder Lake,
so that is exactly the right choice -- the prebuilt was already running kernels compiled
for this microarchitecture before I built anything.

That leaves `-DGGML_NATIVE=ON` with nothing to unlock. `/proc/cpuinfo` reports
`avx2 avx_vnni f16c fma` and **no AVX-512** on this part (Intel fuses AVX-512 off on
consumer 12th/13th gen when E-cores are present, because the E-cores cannot execute it).
The Alder Lake backend already targets precisely that set. `-march=native` can only help
when the CPU has instructions the shipped baseline was not allowed to assume; here there
are none, so the two binaries end up emitting near-identical kernels and the 2% gap is
compiler-version noise, not a real regression.

**The second reason is the one my base track already established.** Even if a smarter
kernel existed, decode on this box is memory-bandwidth-bound, not
instruction-throughput-bound. `benchmarks/01-tuning-tg128.md` shows 1 -> 5 threads buying
only 1.44x for 5x the compute: the memory ceiling arrives long before the arithmetic
ceiling does. A build flag that makes the ALU faster cannot move a number that is set by
how fast weights stream out of LPDDR5. Prefill would have been the fairer place to look
for a compiler win, since prefill *is* compute-bound -- `-p 512` rather than `-n 128`.

**What I would tell someone repeating this:** check
`ls libggml-cpu-*.so` in the release archive **before** spending 15 minutes on a build.
If the release ships a dispatch set that covers your microarchitecture, B1 will measure
compiler noise. The challenge is still worth running on a machine with AVX-512 or on an
architecture the release does not enumerate -- there, `-march=native` has something real
to hand the compiler.
