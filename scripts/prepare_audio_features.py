"""Prepare local registered audio features without loading CUDA or learned models."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="逐曲建立/核验本机音频 DSP 缓存，不改原件，不训练、不上传")
    parser.add_argument("--asset-id", action="append", help="只准备指定的已登记素材；省略则处理全部")
    args = parser.parse_args()
    os.environ.setdefault("PAMOS_ROOT", str(Path(__file__).resolve().parents[1]))
    # Small STFT matrix batches benefit from bounded BLAS threading and must not
    # contend with the workbench or the later, separately started GPU trainer.
    for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    for directory in (Path(os.environ["PAMOS_ROOT"]) / ".tools/ffmpeg").glob("*/bin"):
        if (directory / "ffmpeg.exe").is_file():
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    from phiaimadeos.audio_prepare import prepare_audio_features
    report = prepare_audio_features(asset_ids=args.asset_id,
        progress=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
    print(json.dumps({key: value for key, value in report.items() if key != "items"}, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "succeeded" else 2


if __name__ == "__main__":
    raise SystemExit(main())
