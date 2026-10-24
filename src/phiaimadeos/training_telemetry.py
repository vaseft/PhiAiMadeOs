"""Bounded, cached read-only GPU telemetry. Unavailable never means zero."""
import csv
import os
import subprocess
import threading
import time


class GpuTelemetry:
    def __init__(self):
        self.lock = threading.Lock()
        self.expires = 0
        self.value = None

    def read(self):
        with self.lock:
            if time.monotonic() < self.expires:
                return self.value
            try:
                result = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                    "--format=csv,noheader,nounits", "--id=0"], capture_output=True, text=True, timeout=1.5,
                    creationflags=0x08000000 if os.name == "nt" else 0, check=True)
                row = next(csv.reader(result.stdout.splitlines()))
                def number(index):
                    try:
                        return float(row[index].strip())
                    except (ValueError, IndexError):
                        return None
                self.value = {"utilization_percent": number(0), "memory_used_mib": number(1), "memory_total_mib": number(2),
                              "temperature_c": number(3), "power_w": number(4), "sampled_at": time.time()}
            except (OSError, subprocess.SubprocessError, StopIteration):
                self.value = None
            self.expires = time.monotonic() + 3
            return self.value
