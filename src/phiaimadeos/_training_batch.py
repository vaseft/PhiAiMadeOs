"""Bounded same-song batches; padding never creates or removes targets."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from ._model_data import batch_for

EXECUTION_VERSION = "same-song-padded-window-mean-v1"


def window_chunks(indices, windows, microbatch):
    chunk = []
    for index in indices:
        if chunk and (len(chunk) == microbatch or windows[index].sample_index != windows[chunk[0]].sample_index):
            yield chunk
            chunk = []
        chunk.append(index)
    if chunk:
        yield chunk


def prepare_batch(stage, song, windows, *, pin=False):
    import torch
    rows = [batch_for(stage, song, window, "cpu") for window in windows]
    common, targets = {}, {}

    def padded(values):
        if values[0].ndim < 2:
            return torch.cat(values, dim=0)
        length = max(value.shape[1] for value in values)
        result = values[0].new_zeros((len(values), length, *values[0].shape[2:]))
        for index, value in enumerate(values):
            result[index:index + 1, :value.shape[1]] = value
        return result

    def mask(values):
        lengths = torch.tensor([value.shape[1] for value in values])
        return torch.arange(int(lengths.max()))[None] >= lengths[:, None]

    for key in rows[0][0]:
        values = [row[0][key] for row in rows]
        if isinstance(values[0], torch.Tensor):
            common[key] = padded(values)
            padding_name = {"features": "audio_mask", "notes": "notes_mask", "lines": "lines_mask"}.get(key)
            if padding_name:
                common[padding_name] = mask(values)
            if key == "queries" and stage == "placement":
                common["query_mask"] = mask(values)
        else:
            if any(value != values[0] for value in values):
                raise ValueError("同批窗口的固定模式条件不一致")
            common[key] = values[0]
    for key in rows[0][1]:
        values = [row[1][key] for row in rows]
        targets[key] = padded(values) if isinstance(values[0], torch.Tensor) else values[0]
    if pin:
        common = {key: value.pin_memory() if isinstance(value, torch.Tensor) else value for key, value in common.items()}
        targets = {key: value.pin_memory() if isinstance(value, torch.Tensor) else value for key, value in targets.items()}
    return {"common": common, "targets": targets, "query_lengths": [row[0]["queries"].shape[1] for row in rows],
            "widths": [window.end - window.start for window in windows],
            # Never carry a full parsed song into the GPU consumer/prefetch queue.
            "loss_song": {"parents": list(song["parents"]), "conditions": dict(song["conditions"])}}


def transfer_batch(prepared, device):
    import torch
    return {**prepared, **{section: {key: value.to(device, non_blocking=device.type == "cuda")
                                   if isinstance(value, torch.Tensor) else value
                                   for key, value in prepared[section].items()}
                           for section in ("common", "targets")}}


def loss_rows(stage, prediction, prepared, loss_fn, torch):
    losses, components = [], []
    for index, query_length in enumerate(prepared["query_lengths"]):
        output = {key: (value[index:index + 1, :query_length] if value.ndim >= 2 and key not in {"line_count", "parents"}
                        else value[index:index + 1]) for key, value in prediction.items()}
        target = {key: (value[index:index + 1, :query_length] if value.ndim >= 2 and key != "parents"
                        else value[index:index + 1]) if isinstance(value, torch.Tensor) else value
                  for key, value in prepared["targets"].items()}
        common = {"queries": prepared["common"]["queries"][index:index + 1, :query_length],
                  "width_s": prepared["widths"][index]}
        loss, parts = loss_fn(stage, output, target, common, prepared["loss_song"], torch, synchronize=False)
        losses.append(loss)
        components.append(parts)
    return torch.stack(losses), components


@contextmanager
def batch_executor(enabled):
    if enabled:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="pamos-target-prefetch") as executor:
            yield executor
    else:
        yield None


def prepared_chunks(chunks, prepare, executor=None):
    iterator = iter(chunks)
    if executor is None:
        for chunk in iterator:
            yield chunk, prepare(chunk)
        return
    chunk = next(iterator, None)
    if chunk is None:
        return
    future = executor.submit(prepare, chunk)
    try:
        while chunk is not None:
            result = future.result()
            following = next(iterator, None)
            future = executor.submit(prepare, following) if following is not None else None
            yield chunk, result
            chunk = following
    finally:
        if future is not None and not future.cancel():
            # Do not let a producer retain/mutate the cache after a failed group.
            future.result()
