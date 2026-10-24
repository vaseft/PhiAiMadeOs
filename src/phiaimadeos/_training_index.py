"""Configurable bounded indexing, reusing the unchanged projection/cache code."""
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import multiprocessing

from ._model_data import Window, _index_song, build_windows as serial_or_two


def build_windows(cache, *, progress=None, check_pause=None, workers=1):
    if workers <= 2:
        return serial_or_two(cache, progress=progress, check_pause=check_pause, workers=workers)
    pool = ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context("spawn"))
    pending, results, next_index, completed = {}, {}, 0, 0
    keys = ("chart_id", "group_id", "split", "chart_path", "feature_path", "chart_file_sha256", "chart_sha256", "feature_sha256", "conditions")
    try:
        while completed < len(cache.samples):
            if check_pause:
                check_pause()
            while next_index < len(cache.samples) and len(pending) < workers:
                sample = {key: cache.samples[next_index].get(key) for key in keys}
                pending[pool.submit(_index_song, str(cache.root), sample, cache.max_lines)] = next_index
                next_index += 1
            done, _ = wait(pending, timeout=.25, return_when=FIRST_COMPLETED)
            for future in done:
                index = pending.pop(future)
                results[index] = future.result()
                completed += 1
                if progress:
                    progress(completed, len(cache.samples), results[index][1].get("preparation_cache") or {})
        windows, report = [], []
        for index in range(len(cache.samples)):
            values, row = results.pop(index)
            cache.samples[index].update(row.pop("_verified_input_hashes"))
            windows.extend(Window(index, start, end) for start, end in values)
            report.append(row)
        return windows, report
    finally:
        for future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)
