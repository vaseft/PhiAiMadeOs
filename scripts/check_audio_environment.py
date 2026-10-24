"""Verify the installed audio stack using a disposable, generated signal only."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import librosa
import numpy as np
import soundfile as sf


def main() -> int:
    ffmpeg = shutil.which('ffmpeg')
    ffprobe = shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('Run scripts/environment.cmd first: ffmpeg and ffprobe are required')
    with tempfile.TemporaryDirectory(prefix='pamos-audio-') as temporary:
        root = Path(temporary)
        sample_rate = 22050
        time = np.arange(sample_rate, dtype=np.float32) / sample_rate
        signal = 0.1 * np.sin(2 * np.pi * 440 * time)
        source = root / 'synthetic.wav'
        encoded = root / 'synthetic.flac'
        sf.write(source, signal, sample_rate)
        subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-i', str(source), str(encoded)], check=True)
        probe = subprocess.run([
            ffprobe, '-v', 'error', '-select_streams', 'a:0',
            '-show_entries', 'stream=sample_rate,channels', '-of', 'json', str(encoded),
        ], check=True, capture_output=True, text=True)
        metadata = json.loads(probe.stdout)['streams'][0]
        decoded, actual_rate = sf.read(encoded, dtype='float32')
        mel = librosa.feature.melspectrogram(y=decoded, sr=actual_rate, n_mels=80)
        assert actual_rate == sample_rate and metadata['channels'] == 1
        assert mel.shape[0] == 80 and mel.shape[1] > 0 and np.isfinite(mel).all()
        assert np.max(np.abs(decoded - signal)) < 1e-4
        print(json.dumps({
            'status': 'AUDIO_STACK_PASS', 'source': 'one-second generated sine wave',
            'sample_rate': actual_rate, 'mel_shape': list(mel.shape),
            'soundfile': sf.__version__, 'librosa': librosa.__version__,
            'numpy': np.__version__, 'ffmpeg': Path(ffmpeg).name,
        }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
