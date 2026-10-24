"""Bounded-memory traditional CPU audio analysis, with no learned dependencies."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import uuid

import numpy as np
from scipy import signal

SAMPLE_RATE = 22050
HOP = 882
N_FFT = 2048
FEATURE_VERSION = "dsp-mel80-chroma12-flux8-rms-centroid-rolloff-onset-v1"
MAX_DURATION_S = 7200
MAX_AUDIO_BYTES = 512 * 1024 * 1024


def _hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_audio(path):
    path = Path(path).resolve(strict=True)
    if path.suffix.lower() not in {".wav", ".flac", ".ogg", ".mp3", ".m4a", ".aac"}:
        raise ValueError("仅支持 WAV/FLAC/OGG/MP3/M4A/AAC 音频")
    if path.stat().st_size > MAX_AUDIO_BYTES:
        raise ValueError("音频超过 512 MiB 安全限额")
    warnings = []
    try:
        import soundfile as sf
        info = sf.info(str(path))
        rate, channels, frames = int(info.samplerate), int(info.channels), int(info.frames)
        duration = frames / rate
        decoder = "soundfile"
    except (RuntimeError, ValueError, ImportError):
        executable = shutil.which("ffprobe")
        if not executable or not shutil.which("ffmpeg"):
            raise ValueError("当前解码库不能读取此音频；M4A/AAC 等格式需要本机 FFmpeg/FFprobe")
        process = subprocess.run([executable, "-v", "error", "-protocol_whitelist", "file,pipe", "-select_streams", "a:0",
                                  "-show_entries", "stream=sample_rate,channels,duration:format=duration", "-of", "json", str(path)],
                                 capture_output=True, timeout=30, check=False)
        if process.returncode or len(process.stdout) > 64 * 1024:
            raise ValueError("FFprobe 无法读取音频元数据")
        try:
            data = json.loads(process.stdout)
            stream = data["streams"][0]
            rate, channels = int(stream["sample_rate"]), int(stream["channels"])
            duration = float(stream.get("duration", data.get("format", {}).get("duration")))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            raise ValueError("音频缺少有效时长/声道信息") from exc
        frames, decoder = round(duration * rate), "ffmpeg"
        warnings.append("使用外部 FFmpeg 解码；压缩音频时长取容器元数据，可能有编码延迟")
    if not math.isfinite(duration) or not 0 < duration <= MAX_DURATION_S:
        raise ValueError("音频时长必须在 (0,7200] 秒内")
    if not 1 <= channels <= 8 or not 8000 <= rate <= 192000:
        raise ValueError("音频声道数/采样率超出安全范围")
    return {"duration_s": duration, "sample_rate": rate, "channels": channels,
            "frames": frames, "decoder": decoder, "warnings": warnings, "sha256": _hash_file(path)}


def _samples(path, info):
    """Yield mono 22050 Hz blocks. Seek overlap avoids resampling block seams."""
    total = math.ceil(info["duration_s"] * SAMPLE_RATE)
    if info["decoder"] == "ffmpeg":
        process = subprocess.Popen([shutil.which("ffmpeg"), "-nostdin", "-v", "error", "-protocol_whitelist", "file,pipe",
                                    "-i", str(Path(path).resolve()), "-map", "0:a:0", "-vn", "-sn", "-dn",
                                    "-f", "f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), "pipe:1"],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        seen, residual = 0, b""
        try:
            while True:
                chunk = process.stdout.read(65536 * 4)
                if not chunk:
                    break
                residual += chunk
                count = len(residual) // 4
                values = np.frombuffer(residual[:count * 4], dtype="<f4").copy()
                residual = residual[count * 4:]
                seen += len(values)
                if seen > (MAX_DURATION_S + 1) * SAMPLE_RATE:
                    raise ValueError("解码音频实际时长超过限额")
                yield values
            if residual or process.wait(timeout=10) != 0 or seen == 0:
                raise ValueError("FFmpeg 音频解码失败或数据不完整")
        finally:
            if process.poll() is None:
                process.kill()
            process.stdout.close()
            process.wait(timeout=10)
        return
    import soundfile as sf
    ratio = Fraction(SAMPLE_RATE, info["sample_rate"])
    up, down = ratio.numerator, ratio.denominator
    margin = math.ceil(64 * max(up, down) / up) + down
    with sf.SoundFile(str(path)) as stream:
        for start in range(0, total, 65536):
            end = min(start + 65536, total)
            source_start = max(0, (math.floor(start * down / up) - margin) // down * down)
            source_end = min(info["frames"], math.ceil(end * down / up) + margin)
            stream.seek(source_start)
            chunk = stream.read(source_end - source_start, dtype="float32", always_2d=True)
            mono = chunk.mean(axis=1, dtype=np.float64).astype(np.float32)
            if up != down:
                mono = signal.resample_poly(mono, up, down)
            offset = start - source_start * up // down
            block = mono[offset:offset + end - start]
            if len(block) < end - start:
                block = np.pad(block, (0, end - start - len(block)))
            yield block


def _filterbanks():
    frequencies = np.fft.rfftfreq(N_FFT, 1 / SAMPLE_RATE)
    mel = lambda hz: 2595 * np.log10(1 + hz / 700)
    hz = lambda value: 700 * (10 ** (value / 2595) - 1)
    edges = hz(np.linspace(mel(30), mel(SAMPLE_RATE / 2), 82))
    bank = np.zeros((80, len(frequencies)), dtype=np.float64)
    for index in range(80):
        left, center, right = edges[index:index + 3]
        bank[index] = np.maximum(0, np.minimum((frequencies - left) / (center - left), (right - frequencies) / (right - center)))
        bank[index] /= max(bank[index].sum(), 1e-12)
    chroma = np.zeros((12, len(frequencies)))
    valid = frequencies >= 40
    pitches = np.zeros(len(frequencies), dtype=int)
    pitches[valid] = np.rint(69 + 12 * np.log2(frequencies[valid] / 440)).astype(int) % 12
    for pitch in range(12):
        chroma[pitch, valid & (pitches == pitch)] = 1
    band_edges = np.geomspace(30, SAMPLE_RATE / 2 + 1, 9)
    bands = np.array([(frequencies >= band_edges[i]) & (frequencies < band_edges[i + 1]) for i in range(8)])
    return frequencies, bank, chroma, bands


def _tempo(envelope):
    if len(envelope) < 100 or np.max(envelope, initial=0) < 1e-8:
        return {"bpm": None, "confidence": 0.0, "status": "UNKNOWN", "candidates": []}
    values = envelope - np.mean(envelope)
    correlation = signal.fftconvolve(values, values[::-1], mode="full")[len(values) - 1:]
    lower, upper = round(25 * 60 / 210), min(round(25 * 60 / 55), len(correlation) - 1)
    lags = np.arange(lower, upper + 1)
    scores = correlation[lags] / np.maximum(1, len(values) - lags)
    positive = np.maximum(scores, 0)
    if not len(positive) or positive.max(initial=0) < 1e-12:
        return {"bpm": None, "confidence": 0.0, "status": "UNKNOWN", "candidates": []}
    best = int(np.argmax(positive))
    lag = float(lags[best])
    if 0 < best < len(scores) - 1:
        left, center, right = scores[best - 1:best + 2]
        divisor = left - 2 * center + right
        if abs(divisor) > 1e-12:
            lag += float(np.clip(0.5 * (left - right) / divisor, -0.5, 0.5))
    bpm = 1500 / lag
    variance = float(np.mean(values * values))
    confidence = float(np.clip(positive[best] / max(variance, 1e-12), 0, 1))
    return {"bpm": round(bpm, 5), "confidence": confidence,
            "status": "ESTIMATE" if confidence >= 0.15 else "LOW_CONFIDENCE",
            "candidates": [{"bpm": round(bpm * factor, 5), "relative_factor": factor} for factor in (0.5, 1, 2)]}


def analyze_audio(path, cache_dir, progress=None):
    """Return analysis paths and heuristic evidence; progress(fraction, Chinese text)."""
    info = probe_audio(path)
    cache_dir = Path(cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    prefix = info["sha256"] + "-dsp-v1"
    analysis_path = cache_dir / (prefix + ".json")
    feature_path = cache_dir / (prefix + ".npy")
    waveform_path = cache_dir / (prefix + "-waveform.json")
    if analysis_path.is_file():
        try:
            cached = json.loads(analysis_path.read_text(encoding="utf-8"))
            if (cached.get("feature_version") == FEATURE_VERSION and cached.get("audio_sha256") == info["sha256"]
                    and Path(cached["feature_path"]).resolve() == feature_path and Path(cached["waveform_path"]).resolve() == waveform_path
                    and feature_path.is_file() and waveform_path.is_file()
                    and _hash_file(cached["feature_path"]) == cached.get("feature_sha256")):
                if progress:
                    progress(1.0, "已读取当前版本音频特征缓存")
                return cached
        except (OSError, ValueError, KeyError):
            pass
    temporary = cache_dir / (prefix + "-" + uuid.uuid4().hex + ".tmp.npy")
    expected_frames = math.ceil(info["duration_s"] * SAMPLE_RATE / HOP)
    features = np.lib.format.open_memmap(temporary, mode="w+", dtype="float32", shape=(expected_frames, 104))
    frequencies, melbank, chromabank, bands = _filterbanks()
    window = np.hanning(N_FFT)
    previous = np.zeros(N_FFT // 2 + 1)
    buffer = np.zeros(N_FFT // 2, dtype=np.float32)
    rms_values, peaks, flux_values = [], [], []
    index, decoded, clipped = 0, 0, 0
    def consume(block, final=False):
        nonlocal buffer, previous, index
        buffer = np.concatenate((buffer, block))
        if final:
            buffer = np.pad(buffer, (0, N_FFT))
        available = min((len(buffer) - N_FFT) // HOP + 1, expected_frames - index)
        if available <= 0:
            return
        frames = np.lib.stride_tricks.sliding_window_view(buffer, N_FFT)[::HOP][:available]
        spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
        power = spectrum * spectrum / (N_FFT * N_FFT)
        log_magnitude = np.log1p(spectrum)
        differences = np.maximum(log_magnitude - np.vstack((previous[None, :], log_magnitude[:-1])), 0)
        previous = log_magnitude[-1].copy()
        mel_values = np.log1p(power @ melbank.T * 10000)
        chroma = power @ chromabank.T
        chroma /= np.maximum(chroma.sum(axis=1, keepdims=True), 1e-12)
        band_flux = differences @ bands.T / np.maximum(bands.sum(axis=1), 1)
        rms = np.sqrt(np.mean(frames * frames, axis=1))
        centroid = (spectrum @ frequencies) / np.maximum(spectrum.sum(axis=1), 1e-12) / (SAMPLE_RATE / 2)
        cumulative = np.cumsum(power, axis=1)
        rolloff = np.argmax(cumulative >= cumulative[:, -1:] * 0.85, axis=1) / (N_FFT / 2)
        flux = differences.mean(axis=1)
        result = np.column_stack((mel_values, chroma, band_flux, rms, centroid, rolloff, flux))
        if not np.isfinite(result).all():
            raise ValueError("音频产生了非有限 DSP 特征")
        features[index:index + available] = result.astype(np.float32)
        rms_values.extend(rms.tolist())
        peaks.extend(np.max(np.abs(frames), axis=1).tolist())
        flux_values.extend(flux.tolist())
        index += available
        buffer = buffer[available * HOP:].copy()
    try:
        for block in _samples(path, info):
            if not np.isfinite(block).all():
                raise ValueError("音频样本含 NaN/Infinity")
            decoded += len(block)
            if decoded / SAMPLE_RATE > info["duration_s"] + max(0.25, info["duration_s"] * 0.01):
                raise ValueError("解码时长超出元数据容差，已停止以限制内存与时间")
            clipped += int(np.count_nonzero(np.abs(block) > 1))
            consume(block)
            if progress:
                progress(min(0.9, decoded / max(1, info["duration_s"] * SAMPLE_RATE) * 0.9), "正在分块提取传统 DSP 特征")
        if abs(decoded / SAMPLE_RATE - info["duration_s"]) > max(0.25, info["duration_s"] * 0.01):
            raise ValueError("解码时长与容器元数据明显不一致，不能对齐特征")
        consume(np.empty(0, dtype=np.float32), final=True)
        if index != expected_frames:
            raise ValueError("实际特征帧数与音频时长不一致")
        features.flush()
        del features
        temporary.replace(feature_path)
    except BaseException:
        if "features" in locals():
            del features
        temporary.unlink(missing_ok=True)
        raise
    envelope = np.array(flux_values)
    scale = float(np.percentile(envelope, 95)) if len(envelope) else 0
    normalized = envelope / max(scale, 1e-12)
    local_floor = signal.medfilt(normalized, kernel_size=25) if len(normalized) >= 25 else np.zeros_like(normalized)
    onset_indices, _ = signal.find_peaks(normalized - local_floor, height=0.12, prominence=0.12, distance=2)
    onset_times = (onset_indices * HOP / SAMPLE_RATE).tolist()
    tempo = _tempo(envelope)
    beat_times = []
    if tempo["bpm"] is not None:
        period = 60 / tempo["bpm"]
        phases = np.arange(max(1, round(period * 25))) / 25
        scores = []
        for phase in phases:
            frame_indices = np.rint(np.arange(phase, info["duration_s"], period) * 25).astype(int)
            frame_indices = frame_indices[frame_indices < len(envelope)]
            scores.append(float(envelope[frame_indices].mean()) if len(frame_indices) else 0)
        phase = float(phases[int(np.argmax(scores))])
        beat_times = np.arange(phase, info["duration_s"], period).tolist()
    rms_array = np.array(rms_values)
    threshold = max(1e-5, float(np.percentile(rms_array, 95)) * 0.025)
    quiet = rms_array < threshold
    changes = np.diff(np.r_[False, quiet, False].astype(int))
    silence = [{"start_s": float(start / 25), "end_s": min(info["duration_s"], float(end / 25))}
               for start, end in zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)) if end - start >= 12]
    regions = []
    for start in range(0, len(envelope), 375):
        region = _tempo(envelope[start:start + 750])
        regions.append({"start_s": start / 25, "end_s": min((start + 750) / 25, info["duration_s"]), **region,
                        "provenance": "spectral_flux_autocorrelation"})
    warnings = list(info["warnings"])
    warnings.extend(["BPM/beat 为传统 DSP 启发式估计；半速/倍速与变 BPM 需人工确认", "置信度表示周期稳定程度，不是模型概率或谱面质量", "音画偏移/客户端试听 NOT RUN"])
    if tempo["status"] != "ESTIMATE":
        warnings.append("节拍证据不足；不会把默认 BPM 冒充测量结果")
    if clipped:
        warnings.append(f"检测到 {clipped} 个幅值超过 1 的样本；仅报告，未自动改音频")
    waveform = {"peaks": peaks, "duration_s": info["duration_s"], "hop": HOP, "sample_rate": SAMPLE_RATE,
                "frame_time": "centered_at_index_times_hop", "version": FEATURE_VERSION}
    waveform_path.write_text(json.dumps(waveform, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    result = {"feature_path": str(feature_path), "waveform_path": str(waveform_path), "analysis_path": str(analysis_path),
              "onsets_s": onset_times, "onset_strength": normalized[onset_indices].tolist(),
              "bpm": tempo["bpm"], "beat_times_s": beat_times, "duration_s": info["duration_s"],
              "sample_rate": SAMPLE_RATE, "original_sample_rate": info["sample_rate"], "channels": info["channels"],
              "hop": HOP, "frame_rate": 25, "feature_dim": 104, "feature_version": FEATURE_VERSION,
              "feature_layout": {"mel_log_power": [0, 80], "chroma": [80, 92], "band_flux": [92, 100],
                                 "rms": 100, "centroid_normalized": 101, "rolloff_normalized": 102, "spectral_flux": 103},
              "feature_sha256": _hash_file(feature_path), "audio_sha256": info["sha256"],
              "rms_curve": rms_values, "rms_hop_s": 0.04, "silence_intervals": silence,
              "silence_rms_threshold": threshold, "tempo": tempo, "tempo_regions": regions,
              "confidence": tempo["confidence"], "provenance": "traditional_cpu_dsp", "warnings": warnings}
    temporary_json = analysis_path.with_name(analysis_path.name + "." + uuid.uuid4().hex + ".tmp")
    temporary_json.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary_json.replace(analysis_path)
    if progress:
        progress(1.0, "音频 DSP 特征已保存；仍需人工确认节拍与偏移")
    return result
