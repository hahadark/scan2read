"""Compare sequential rendering/OCR with one-page process prefetch.

Experimental measurement only: does not change production or its OCR cache.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import multiprocessing
from pathlib import Path
import statistics
import subprocess
import threading
import time

from scan2read.pdf.renderer import render_page


def render(source, number, destination):
    start = time.perf_counter()
    render_page(Path(source), number, Path(destination), 300)
    return time.perf_counter() - start


def ready():
    return True


class Monitor:
    def __init__(self):
        self.samples = []
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                result = subprocess.run(
                    ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used', '--format=csv,noheader,nounits'],
                    capture_output=True, text=True, timeout=3,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.samples.append([float(s.strip()) for s in result.stdout.strip().splitlines()[0].split(',')])
            except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
                pass
            self.stop.wait(.4)


def measure(engine, source, numbers, output, mode, executor=None):
    output.mkdir(parents=True, exist_ok=True)
    monitor = Monitor()
    thread = threading.Thread(target=monitor.run)
    thread.start()
    rows = []
    start = time.perf_counter()
    future = None
    if mode == 'prefetch':
        future = executor.submit(render, source, numbers[0], output / f'{numbers[0]}.png')
    for index, number in enumerate(numbers):
        path = output / f'{number}.png'
        wait_start = time.perf_counter()
        render_seconds = future.result() if future else render(source, number, path)
        wait_seconds = time.perf_counter() - wait_start
        if mode == 'prefetch' and index+1 < len(numbers):
            following = numbers[index+1]
            future = executor.submit(render, source, following, output / f'{following}.png')
        ocr_start = time.perf_counter()
        page = engine.recognize(path)
        ocr_seconds = time.perf_counter() - ocr_start
        data = page.to_json()
        if not isinstance(data, str):
            data = json.dumps(data, sort_keys=True)
        rows.append({'page': number, 'render_s': render_seconds, 'wait_s': wait_seconds,
                     'ocr_s': ocr_seconds, 'ocr_sha256': hashlib.sha256(data.encode()).hexdigest(),
                     'image_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    elapsed = time.perf_counter() - start
    monitor.stop.set()
    thread.join()
    result = {'mode': mode, 'elapsed_s': elapsed, 'per_page_s': elapsed/len(numbers),
              'render_total_s': sum(r['render_s'] for r in rows),
              'wait_total_s': sum(r['wait_s'] for r in rows),
              'ocr_total_s': sum(r['ocr_s'] for r in rows), 'pages': rows,
              'gpu_mean_percent': statistics.mean(r[0] for r in monitor.samples) if monitor.samples else None,
              'gpu_max_percent': max((r[0] for r in monitor.samples), default=None),
              'gpu_peak_memory_mib': max((r[1] for r in monitor.samples), default=None)}
    print(json.dumps({k:v for k,v in result.items() if k!='pages'}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('--output', type=Path, default=Path('output/gpu-prefetch-benchmark'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    from scan2read.ocr.paddle import PaddleEngine
    start = time.perf_counter()
    engine = PaddleEngine(device='gpu:0')
    model_load = time.perf_counter() - start
    numbers = list(range(28, 36))
    warm = args.output / 'warmup.png'
    render(args.source, numbers[0], warm)
    for _ in range(2):
        engine.recognize(warm)
    results = []
    # Reverse the order on round two to reduce cache/thermal order bias.
    for round_number, modes in enumerate((('sequential','prefetch'),('prefetch','sequential')), 1):
        for mode in modes:
            destination = args.output / f'{round_number}-{mode}'
            if mode == 'prefetch':
                pool_start = time.perf_counter()
                with ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn')) as executor:
                    executor.submit(ready).result()
                    pool_startup = time.perf_counter()-pool_start
                    result = measure(engine,args.source,numbers,destination,mode,executor)
                    result['worker_startup_s'] = pool_startup
            else:
                result = measure(engine,args.source,numbers,destination,mode)
            results.append(result)
            (args.output/'results.json').write_text(json.dumps({'model_load_s':model_load,'runs':results},indent=2),encoding='utf-8')
    baseline = results[0]['pages']
    equivalent = all([(r['image_sha256'],r['ocr_sha256']) for r in run['pages']] ==
                     [(r['image_sha256'],r['ocr_sha256']) for r in baseline] for run in results)
    summary = {'model_load_s':model_load, 'runs':results, 'identical_images_and_ocr':equivalent}
    (args.output/'results.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print('IDENTICAL_IMAGES_AND_OCR', equivalent, flush=True)


if __name__ == '__main__':
    main()
