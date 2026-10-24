#!/usr/bin/env python3
"""Synthetic forward/backward/AMP/AdamW/accumulation memory benchmark.

Models a small audio-conditioned event decoder at explicit max window shapes.
Not a real chart generation model and NOT evidence of chart quality.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--steps', type=int, default=100, help='Actual optimizer steps; each has grad-accum microsteps')
    parser.add_argument('--grad-accum', type=int, default=16)
    parser.add_argument('--microbatch', type=int, default=1)
    parser.add_argument('--audio-frames', type=int, default=384)
    parser.add_argument('--note-slots', type=int, default=192)
    parser.add_argument('--feature-dim', type=int, default=104)
    parser.add_argument('--d-model', type=int, default=192)
    parser.add_argument('--layers', type=int, default=4)
    parser.add_argument('--max-vram-gb', type=float, default=6.2)
    parser.add_argument('--max-rss-gb', type=float, default=6.0)
    parser.add_argument('--output', default='runs/gpu_profile_synthetic.json')
    args = parser.parse_args()
    if min(args.steps, args.grad_accum, args.microbatch, args.audio_frames, args.note_slots) < 1:
        parser.error('steps, accum, batch and token counts must be positive')
    if args.d_model % 4:
        parser.error('d-model must be divisible by 4')

    try:
        import torch
        from torch import nn
        from torch.nn import functional as F
    except ImportError:
        print('torch missing: install compatible CUDA wheel first', file=sys.stderr)
        return 2
    if not torch.cuda.is_available():
        print('CUDA not available; do not mark GPU PROFILE_PASS', file=sys.stderr)
        return 2

    device = torch.device('cuda:0')
    initial_free, initial_total = torch.cuda.mem_get_info(0)
    print(f'CUDA free before benchmark: {initial_free/1024**3:.3f} GiB / {initial_total/1024**3:.3f} GiB', flush=True)
    torch.manual_seed(20261024)
    class EventPredictor(nn.Module):
        def __init__(self):
            super().__init__()
            d = args.d_model
            self.audio_proj = nn.Linear(args.feature_dim, d)
            self.audio_pos = nn.Embedding(args.audio_frames, d)
            self.note_pos = nn.Embedding(args.note_slots, d)
            self.audio = nn.TransformerEncoder(
                nn.TransformerEncoderLayer(d, 4, 4*d, dropout=0.1, batch_first=True),
                num_layers=2,
                enable_nested_tensor=False,
            )
            self.decoder = nn.TransformerDecoder(
                nn.TransformerDecoderLayer(d, 4, 4*d, dropout=0.1, batch_first=True),
                num_layers=args.layers,
            )
            self.classifier = nn.Linear(d, 5)
            self.time_offset = nn.Linear(d, 1)
        def forward(self, feats):
            b, t, _ = feats.shape
            a_ids = torch.arange(t, device=feats.device)
            n_ids = torch.arange(args.note_slots, device=feats.device)
            encoded = self.audio(self.audio_proj(feats) + self.audio_pos(a_ids))
            queries = self.note_pos(n_ids).unsqueeze(0).expand(b, -1, -1)
            predicted = self.decoder(queries, encoded)
            return self.classifier(predicted), self.time_offset(predicted).squeeze(-1)

    model = EventPredictor().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-4)
    dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
    scaler = torch.amp.GradScaler('cuda', enabled=(dtype == torch.float16))
    torch.cuda.reset_peak_memory_stats()
    rss_peak = 0.0
    start = time.monotonic()
    report = {
        'kind': 'SYNTHETIC_ONLY_NOT_REAL_TRAINING',
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'gpu': torch.cuda.get_device_name(0),
        'torch': torch.__version__,
        'torch_cuda': torch.version.cuda,
        'config': vars(args),
        'params': sum(p.numel() for p in model.parameters()),
        'dtype': str(dtype),
        'initial_gpu_free_gib': round(initial_free / 1024**3, 3),
        'result': 'UNTESTED',
    }
    try:
        import psutil
        process = psutil.Process(os.getpid())
    except ImportError:
        process = None
    if process is None:
        print('psutil missing; cannot verify host RSS budget. pip install -r requirements/base.txt', file=sys.stderr)
        return 2
    try:
        for step in range(args.steps):
            model.train()
            optimizer.zero_grad(set_to_none=True)
            for j in range(args.grad_accum):
                # Synthetic bounded input for testing PyTorch runtime and memory only.
                feats = torch.randn(args.microbatch, args.audio_frames, args.feature_dim, device=device)
                target = torch.randint(0, 5, (args.microbatch, args.note_slots), device=device)
                residual_target = torch.zeros(args.microbatch, args.note_slots, device=device)
                with torch.autocast(device_type='cuda', dtype=dtype):
                    logits, residual = model(feats)
                    loss = F.cross_entropy(logits.reshape(-1, 5).float(), target.reshape(-1))
                    loss += 0.1 * F.smooth_l1_loss(residual.float(), residual_target)
                    loss = loss / args.grad_accum
                scaler.scale(loss).backward()
                if process:
                    rss_peak = max(rss_peak, process.memory_info().rss / 1024**3)
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
            if (step + 1) % 10 == 0:
                torch.cuda.synchronize()
                print(f'step={step + 1} loss_micro={float(loss.item()):.4f} '
                      f'gpu_reserved={torch.cuda.max_memory_reserved()/1024**3:.3f}GiB '
                      f'rss_peak={rss_peak:.3f}GiB', flush=True)
        torch.cuda.synchronize()
        report.update({
            'result': 'PROFILE_PASS' if (torch.cuda.max_memory_reserved()/1024**3 <= args.max_vram_gb and rss_peak <= args.max_rss_gb) else 'PROFILE_OVER_BUDGET',
            'seconds': round(time.monotonic()-start, 2),
            'vram_reserved_peak_gib': round(torch.cuda.max_memory_reserved()/1024**3, 3),
            'vram_allocated_peak_gib': round(torch.cuda.max_memory_allocated()/1024**3, 3),
            'rss_peak_gib': round(rss_peak, 3),
            'remark': 'Pass does NOT guarantee real-data trainability; profile a full real-data epoch next.',
        })
    except torch.cuda.OutOfMemoryError as exc:
        report['result'] = 'OOM'
        report['error'] = str(exc)
    except Exception as exc:
        report['result'] = 'FAILED'
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        report.setdefault('seconds', round(time.monotonic()-start, 2))
        report.setdefault('vram_reserved_peak_gib', round(torch.cuda.max_memory_reserved()/1024**3, 3))
        report.setdefault('vram_allocated_peak_gib', round(torch.cuda.max_memory_allocated()/1024**3, 3))
        report.setdefault('rss_peak_gib', round(rss_peak, 3))
        p = Path(args.output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if report['result'] == 'PROFILE_PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
