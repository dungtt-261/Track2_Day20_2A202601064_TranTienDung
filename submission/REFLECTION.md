# Reflection — Day 20 Lab (Personal Report)

**Họ Tên:** Trần Tiến Dũng (2A202601064)
**Cohort:** Cohort 3B
**Ngày submit:** 2026-08-20

---

## 1. Hardware & runtime  *(rubric 1, 2 — 10 điểm)*

- **OS:** Linux 7.1.6-1-cachyos (CachyOS, x86_64)
- **CPU:** 13th Gen Intel Core i5-1335U
- **Cores:** 10 physical / 12 logical — thực chất là **2 P-core (4.6 GHz, có SMT) + 8 E-core (3.4 GHz, không SMT)**
- **CPU extensions:** AVX2
- **RAM:** 15.3 GB
- **Accelerator:** không có (CPU only — máy chỉ có iGPU Intel Iris Xe, `ngl=0`)
- **llama.cpp asset đã tải:** `llama-b10488-bin-ubuntu-x64.tar.gz` (16.7 MB, prebuilt, không compile)
- **Model đã dùng:** Gemma 4 E2B (`LAB_MODEL=gemma4-e2b`)
- **Quantization:** UD-Q4_K_XL (primary) + UD-Q2_K_XL (compare)

**Chạy ở đâu:** laptop của tôi. Không dùng Colab/Kaggle.

**Setup story:** Trước khi bắt đầu tôi đã có sẵn một file `gemma-4-E2B-it-Q4_0.gguf`
tải thủ công. Nó vô dụng với lab: sai quantization (Q4_0 legacy, không phải UD-Q4_K_XL)
và chỉ có một quant nên không so sánh được. Tôi xoá và chạy `make setup` để lấy đúng
cặp UD. Ngoài ra không có bước nào fail. Điểm cần lưu ý duy nhất là `make probe` báo
`GPU offload OFF` — đúng thực tế, máy không có GPU rời.

---

## 2. Đo lường  *(rubric 3, 4, 5 — 20 điểm)*

> Từ `benchmarks/01-quickstart-results.md` (`make bench`, `threads=10`, `ngl=0`, `ctx=2048`, `max_tokens=64`).

| Quantization | Size (GB) | Load (ms) | TTFT P50/P95 (ms) | TPOT P50/P95 (ms) | E2E P50/P95/P99 (ms) | Decode (tok/s) |
|---|--:|--:|--:|--:|--:|--:|
| UD-Q4_K_XL | 2.97 | 5112 | 969 / 1619 | 175.3 / 190.4 | 11784 / 13303 / 13303 | 5.7 |
| UD-Q2_K_XL | 2.24 | 8140 | 1428 / 1713 | 169.9 / 189.4 | 12309 / 13262 / 13262 | 5.9 |

**Quan sát:** 2-bit **không đáng**. Nó chỉ nhanh hơn 1.04× khi decode nhưng TTFT **tệ
hơn 1.47×**, đổi lấy 0.73 GB đĩa. Lý do: `ngl=0` nên mọi weight phải dequantize trên
CPU, và Q2_K chia super-block thành 16 sub-block 16-weight (Q4_K: 8 sub-block 32-weight)
nên tốn gấp đôi phép scale mỗi weight — ăn hết phần tiết kiệm bandwidth. Tôi hỏi cùng
một câu trên cả hai (:8080 vs :8090), chất lượng không phân biệt được. Chỉ đáng dùng
nếu thiếu RAM.

---

## 3. Serving under load  *(rubric 8, 9, 10 — 20 điểm)*

> Từ `benchmarks/02-server-results.md` (`make load-report`). Server chạy `-t 5 -ngl 0 --ctx-size 2048 --parallel 4 --cont-batching`.

| Users | RPS | P50 (ms) | P95 (ms) | P99 (ms) | Eff. concurrency | Failures |
|--:|--:|--:|--:|--:|--:|--:|
| 10 | 0.16 | 47000 | 51000 | 51000 | 5.0 | 0.0% |
| 50 | 0.21 | 19000 | 19000 | 19000 | 3.7 | 0.0% |

- **Offered load tăng 5×, throughput thực tăng:** 1.34× (27% của linear)
- **P95 tăng:** 0.37× — tức là **giảm**, và đây là artefact, xem giải thích bên dưới
- **Effective concurrency ở 50 users:** 3.7 so với `--parallel` = 4 slots

**Peak `llamacpp:n_busy_slots_per_decode`** (từ `make metrics` chạy chồng với
`make load-50`): 3.67 / 4 slots (92%), `requests_deferred` peak = 46

**Saturation reading:** Server bão hoà đúng ở 4 request đồng thời — bằng `--parallel`.
Bằng chứng thuyết phục tôi là `requests_deferred = 46` (= 50 users − 4 slots), không
phải bảng trên. **P95 "giảm" 0.37× là survivorship bias**: locust chỉ tính request
hoàn thành trong 60s; ở 50 users chỉ 4 request `short` kịp xong, còn `long-rag` (50.5s)
không cái nào xong nên bị loại khỏi mẫu. Latency thêm vào là **queue time** — server
gauge chứng minh điều đó, client-side thì không. Để nâng goodput@SLO tôi cắt
`max_tokens` trước, **không** tăng `--parallel`: `ctx=2048` chia cho 4 slot = 512
token/slot, mà `long-rag` đã dùng 356; lên `--parallel 8` thì slot còn 256 và những
request đó **fail hẳn**, chưa kể thêm slot không thêm bandwidth trên CPU.

---

## 4. Integration  *(rubric 12, 13 — 15 điểm)*

> Từ `make pipeline`. Khai báo trung thực — stub **không** mất điểm.

| Day | Piece | Real hay stub? |
|---|---|---|
| N16 Cloud/IaC | không có — chỉ localhost, không cluster/Compose/IaC | **stub** |
| N17 Data pipeline | không có DAG/batch job — dùng list `TOY_DOCS` in-memory | **stub** |
| N18 Lakehouse | không Delta/Iceberg, không cả SQLite — cùng list in-memory | **stub** |
| N19 Vector + features | không vector index, không embedding model — chạy không có `--embed-url` nên rơi về keyword overlap | **stub** |
| N20 Serving | `llama-server` | real |

**Latency split** (mean của 3 query):

- embed: 0.0 ms
- retrieve: 0.1 ms
- llm: 9197.6 ms
- **stage chiếm nhiều nhất:** llm (100% của total)

**Reflection:** Đúng kỳ vọng là llm dominate, nhưng bất ngờ nằm **bên trong** stage đó:
prefill mất 2964/6633/5529 ms so với decode 4884/3783/3690 ms — prefill là **một nửa**
wall clock cho prompt chỉ 113–149 token. Vì `ngl=0` nên prefill chạy cùng 2 P-core với
decode, không có GPU nuốt nó trong một pass. Muốn giảm 2× tôi đánh vào prompt caching
trước (`SYSTEM_PROMPT` là hằng số, prefix tái dùng được), không phải đổi quantization.

---

## 5. The single change that mattered most  *(rubric 11 — 10 điểm)*

**Change:** hạ `-t` từ 10 (mặc định = physical core count) xuống **5**.

```
before:  6.7 tok/s   (-t 10, tg128, llama-bench)
after:   7.5 tok/s   (-t 5,  tg128, llama-bench)
speedup: 1.11×
```

**Tại sao nó work:**

`hardware.json` báo "10 physical · 12 logical", đọc lên như một CPU 10 nhân đồng nhất.
Nó không phải. Đọc `/sys/devices/system/cpu/`: cpu0–cpu3 chạy 4.6 GHz và đi theo cặp
SMT (0-1, 2-3) — đó là **2 P-core**; cpu4–cpu11 chạy 3.4 GHz, không sibling — đó là **8
E-core**. Hai loại nhân này không thay thế nhau được: E-core thấp hơn 1.35× xung nhịp
*và* có vector unit hẹp hơn, nên cùng một phần việc AVX2 GEMM thì P-thread xong nhanh
hơn hẳn. ggml chia mỗi tensor op thành các chunk **bằng nhau**, mỗi thread một chunk,
rồi join ở barrier trước op kế tiếp — vài chục barrier cho mỗi token decode. Barrier chỉ
xong khi **thread chậm nhất** xong. Chunk bằng nhau trên nhân không bằng nhau nghĩa là
P-core đứng chờ ở barrier gần hết mỗi op. Mỗi thread E-core thêm vào sau knee là thêm
một straggler, không phải thêm throughput. Đó là lý do peak nằm ở 5 chứ không phải 10.

Phần còn lại của curve khớp với cùng một cơ chế. 1→5 thread chỉ được 1.44× cho 5× số
thread: decode bị chặn bởi memory bandwidth nên phần lớn parallelism không bao giờ
chuyển thành tốc độ — trần bộ nhớ xuất hiện trước trần số nhân. 10→12 tụt 4% vì hai
thread cuối là SMT sibling trên P-core: hai hyperthread dùng chung một bộ vector unit
nên mỗi P-thread còn ~60% tốc độ, biến chính các thread nhanh thành straggler (SMT hại
ở kernel dense-FP vì không còn latency nào để giấu). 12→24 tụt về 5.2 — đúng bằng con
số single-thread — vì oversubscribe 2×: mỗi barrier đều có thành viên bị descheduled,
phần còn lại phải chờ nó được xếp lại. Việc throughput rơi về mức 1 thread là dấu hiệu
rõ nhất rằng lúc đó **barrier**, không phải phép tính, mới là bottleneck. Spread toàn
sweep là 1.43×, nên chọn sai thread count đắt hơn phần lớn knob khác trong lab này mua
lại được. Tôi có kiểm chứng end-to-end (`make smoke` với `-t 5` báo 11.7–12.4 tok/s qua các lần chạy, so với
5.7 tok/s của `make bench` ở `-t 10`), nhưng con số tôi **claim** là 1.11× từ sweep có
kiểm soát, vì lần chạy sau đã ấm page cache nên 2× kia không phải so sánh công bằng.

---

## 6. Bonus  *(optional — tối đa 20 điểm)*

**Đã làm:** B1 `build-llama` + `compare-builds` · B2 `sweep-batch` · B4 challenge **C2**
(KV cache quantization) · B5 challenge **C9** (embedding serving regime).
Chi tiết: `benchmarks/bonus-build-compare-tg128.md`, `bonus-batch-size-sweep.md`,
`bonus-c2-kv-quant.md`, `bonus-c9-embedding-regime.md`.

**Numbers** (B1 — prebuilt release vs bản tôi tự compile, cùng revision `b10488`, cùng
model, cùng `ngl=0`, metric `tg128`):

```
before:  6.8 tok/s   (prebuilt release, runtime CPU dispatch)
after:   6.7 tok/s   (source build, -DGGML_NATIVE=ON)
speedup: 0.98×
```

**Điều này nói lên gì mà deck chưa nói:**

Bonus README nói máy CPU-only yếu sẽ thắng đậm nhất ở B1, vì prebuilt binary "phải chạy
được trên nhiều máy nên chỉ nhắm tới một CPU baseline chung". **Tiền đề đó đã lỗi thời.**
Prebuilt `b10488` ship **14 file `libggml-cpu-*.so`** và chọn bằng CPUID lúc load; trên
máy này nó nạp `libggml-cpu-alderlake.so`. i5-1335U là Raptor Lake-P, cùng thế hệ ISA với
Alder Lake, nên prebuilt **đã** chạy kernel biên dịch cho đúng microarchitecture này từ
trước khi tôi build gì cả. `/proc/cpuinfo` chỉ có `avx2 avx_vnni f16c fma`, **không có
AVX-512** (Intel fuse tắt khi chip có E-core), nên `-march=native` không còn gì để mở
khoá và 2% chênh lệch là nhiễu phiên bản compiler (GNU 11.4.0 vs 16.1.1).

Nhưng phát hiện thật sự của bonus track không nằm ở một con số nào, mà ở việc **ba thí
nghiệm độc lập cùng thất bại theo đúng một kiểu**:

| Thí nghiệm | Knob | Kỳ vọng | Đo được |
|:--|:--|--:|--:|
| B1 compare-builds | kernel `-march=native` | thắng đậm | **0.98×** |
| B2 sweep-batch | `-ub` 128→512 (tái dùng weight 4×) | cải thiện rõ | **1.07×** |
| C9 embedding | static batch 1→16 | tăng mạnh | **1.29× rồi phẳng** |

Cả ba knob đều hoạt động bằng cách **giảm memory traffic trên mỗi đơn vị công việc**, và
cả ba đều không trả về gì. Ghép với base track — decode chỉ được 1.44× từ 5× số thread —
bức tranh nhất quán và rất cụ thể cho máy này:

- **Prefill** (và embedding, vốn toàn là prefill) bị chặn bởi **compute**. Knob amortize
  memory read không có gì để amortize; ALU đã là bức tường.
- **Decode** bị chặn bởi **memory bandwidth**. Knob thêm compute không có gì để nuôi;
  bus bộ nhớ mới là bức tường.

Mọi tối ưu tôi thử trong bonus track đều nhắm sai vế của cặp này. C2 củng cố cùng bài
học từ phía RAM: KV cache của Gemma 4 E2B chỉ ~22 MB ở `ctx=2048` và ~78 MB ở `ctx=8192`
(model chia sẻ KV qua 20/35 layer), tức 0.6–1.9% của RSS, trong khi weight chiếm ~3.0 GB.
Quantize KV tiết kiệm 11–39 MB — giải một bài toán mà laptop này không có.

Deck dạy "prefill compute-bound, decode memory-bound" như một slide phân loại. Điều tôi
học được khi đo là nó không phải phân loại — nó là **quy tắc chọn knob**. Trên phần cứng
này, biết mình đang tối ưu phase nào quan trọng hơn mọi con số trong bảng ở trên.

## 7. Điều làm bạn ngạc nhiên nhất  *(optional)*

Hai con số bằng nhau vì hai lý do trái ngược: effective concurrency phía client (3.7) và
peak busy slots phía server (3.67) trùng nhau gần như tuyệt đối, nhưng cái đầu *đáng lẽ*
phải lớn hơn 4 vì có 46 request đang xếp hàng — nó nhỏ là do locust chỉ trung bình trên
các request đã hoàn thành. Hai số khớp nhau vì sai số triệt tiêu còn nguy hiểm hơn hai
số lệch nhau.

---

## 8. Self-check trước khi push

- [x] `hardware.json` committed
- [x] `models/active.json` committed
- [x] `benchmarks/01-quickstart-results.md` committed (`make bench`)
- [x] `benchmarks/01-tuning-tg128.md` committed (`make tune`)
- [x] `benchmarks/02-server-results.md` committed (`make load-report`)
- [x] `benchmarks/02-server-batching-u50.md` + `-metrics-u50.csv` committed (`make metrics`)
- [x] `benchmarks/locust-10_stats.csv` + `locust-50_stats.csv` committed (`make load-10` / `load-50`)
- [x] `benchmarks/03-integration-results.md` committed (`make pipeline`)
- [x] Mọi section **"required — replace this line"** đã được thay bằng nhận xét của tôi
- [ ] 5 screenshots trong `submission/screenshots/`
- [ ] `make verify` → **exit 0**
- [ ] Repo GitHub ở chế độ **public**
- [ ] Đã paste public URL vào VinUni LMS
- [x] **Không** commit `models/*.gguf` hay `runtime/` (đã có trong `.gitignore`)
