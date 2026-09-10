# GPU render-ahead benchmark — 2026-09-08

RTX 3070, current PaddleOCR Korean mobile models, recognition batch 16, 300 DPI.
Source: 고대 근동 문화.pdf, PDF pages 28–35 (8 pages), forced image OCR.
A standalone benchmark used the production renderer and OCR adapter. No production behavior or conversion cache was changed.

Two rounds: sequential → prefetch, then prefetch → sequential. One separate spawned rendering process prepares at most the next page while the main process performs GPU OCR. The engine was warmed twice before timing. Each run rendered fresh PNG files; OS file caching was warm for both modes.

| Measurement | Sequential | Prefetch |
|---|---:|---:|
| Mean 8-page rendering + OCR | 5.423 s | 4.160 s |
| Seconds/page | 0.678 | 0.520 |
| Mean sampled GPU utilization (whole device) | 35.5% | 41.8% |

Processing time decreased 23.3%; throughput increased 30.4%.
The prefetch worker adds 0.352 s of startup per run. Including this overhead gives 4.513 s versus 5.423 s (16.8% less time for this short sample).
Model construction took 5.326 s and is excluded from both modes, as are spacing, EPUB generation, validation, and production cache persistence. These numbers are not full-book conversion timings.

Rendered image bytes and complete OCR JSON (text, boxes, confidence, reading order) were identical in all four runs: True.
GPU readings were sampled through nvidia-smi approximately every 0.4 s and reflect the whole device, including other applications; short-window GPU percentages are noisy. Judge this result mainly by elapsed time. No promise of proportional speedup for other books or already-cached OCR.

The runtime emitted a pre-existing cuDNN version mismatch warning (compiled 9.9, loaded 9.5). All tested runs completed and returned matching results; dependencies were not changed during the benchmark.

Reproduce:
```powershell
$env:PYTHONPATH = 'src'
$env:PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK = 'True'
.tools/paddle-env/Scripts/python scripts/benchmark_prefetch.py 'PATH_TO_PDF'
```

Raw measurements: output/gpu-prefetch-benchmark/results.json
