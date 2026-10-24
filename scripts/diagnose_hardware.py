#!/usr/bin/env python3
"""Read-only device/driver/CUDA diagnostic for PhiAiMadeOs.

Exit 0: device usable for basic CUDA backward; exit 1: cannot use requested CUDA.
Does NOT prove the full project can train on this GPU.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-cuda', action='store_true')
    parser.add_argument('--output', default='runs/environment.json')
    args = parser.parse_args()
    report = {
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'python': sys.version,
        'platform': platform.platform(),
        'logical_cpus': os.cpu_count(),
        'status': 'UNTESTED',
    }
    try:
        import psutil
        vm = psutil.virtual_memory()
        report['system_memory_gib'] = round(vm.total / 1024**3, 3)
        report['system_available_gib'] = round(vm.available / 1024**3, 3)
    except ImportError:
        report['system_memory'] = 'psutil not installed'
    du = shutil.disk_usage(Path.cwd())
    report['disk_free_gib'] = round(du.free / 1024**3, 3)
    try:
        smi = subprocess.run(
            ['nvidia-smi', '--query-gpu=name,memory.total,memory.free,driver_version', '--format=csv,noheader'],
            capture_output=True, text=True, timeout=10, check=False,
        )
        report['nvidia_smi'] = (smi.stdout or smi.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        report['nvidia_smi'] = f'unavailable: {exc}'
    try:
        import torch
        report['torch_version'] = torch.__version__
        report['torch_cuda_runtime'] = torch.version.cuda
        report['cuda_available'] = bool(torch.cuda.is_available())
        if torch.cuda.is_available():
            prop = torch.cuda.get_device_properties(0)
            report['device_name'] = prop.name
            report['capability'] = list(torch.cuda.get_device_capability(0))
            report['supported_arches'] = torch.cuda.get_arch_list()
            report['total_vram_gib'] = round(prop.total_memory / 1024**3, 3)
            free, total = torch.cuda.mem_get_info(0)
            report['cuda_free_vram_gib'] = round(free / 1024**3, 3)
            report['amp_bfloat16_available'] = bool(torch.cuda.is_bf16_supported())
            # Real forward + backward, not a bare CUDA-is-available check.
            x = torch.randn(256, 256, device='cuda', requires_grad=True)
            y = (x @ x).square().mean()
            y.backward()
            torch.cuda.synchronize()
            report['backward_on_cuda'] = bool(x.grad is not None and torch.isfinite(x.grad).all().item())
            del x, y
            report['status'] = 'CUDA_READY' if report['backward_on_cuda'] else 'CUDA_FAILED'
        else:
            report['status'] = 'CUDA_NOT_AVAILABLE'
    except Exception as exc:
        report['status'] = 'CUDA_ERROR'
        report['error'] = f'{type(exc).__name__}: {exc}'
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.require_cuda and report['status'] != 'CUDA_READY':
        print('FAIL: GPU training compatibility is not verified.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
