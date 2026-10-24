"""Import only the explicit user-provided local source directory."""
import argparse
import json
from pathlib import Path
import os


def main():
    parser = argparse.ArgumentParser(description="把本机 ZIP/PEZ 谱面批量导入 PAMOs；不训练、不改变许可、不上传素材")
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    os.environ.setdefault("PAMOS_ROOT", str(Path(__file__).resolve().parents[1]))
    for directory in (Path(os.environ["PAMOS_ROOT"]) / ".tools/ffmpeg").glob("*/bin"):
        if (directory / "ffmpeg.exe").is_file():
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
    from phiaimadeos.library_import import import_library
    result = import_library(args.source, progress=lambda value: print(json.dumps(value, ensure_ascii=False), flush=True))
    print(json.dumps({k: v for k, v in result.items() if k not in {"items", "source_path"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
