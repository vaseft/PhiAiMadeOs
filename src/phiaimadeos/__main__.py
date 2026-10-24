"""Run one loopback-only workbench and its independent subprocess jobs."""
import argparse
from contextlib import contextmanager
import os
from pathlib import Path
import sys


@contextmanager
def singleton(root):
    path = root / ".local/workbench.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise SystemExit("PAMOs 已在此目录运行。请打开 http://127.0.0.1:8765") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description="PhiAiMadeOs 本地工作台")
    parser.add_argument("--root", type=Path, help="仓库根目录；默认 PAMOS_ROOT")
    args = parser.parse_args()
    if args.root:
        os.environ["PAMOS_ROOT"] = str(args.root.resolve())
    from .settings import get_settings
    settings = get_settings()
    for folder in (settings.root / ".tools/ffmpeg").glob("*/bin"):
        if (folder / "ffmpeg.exe").exists():
            os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
    for name, suffix in {"NUMBA_CACHE_DIR": "numba", "TORCH_HOME": "torch", "HF_HOME": "huggingface", "XDG_CACHE_HOME": ""}.items():
        os.environ.setdefault(name, str(settings.root / ".cache" / suffix))
    os.environ["PYTHONUTF8"] = "1"
    with singleton(settings.root):
        import uvicorn
        print("PhiAiMadeOs 本地工作台：http://127.0.0.1:8765\n本轮功能未运行测试；真实训练与客户端试玩需用户提供授权素材。", flush=True)
        uvicorn.run("phiaimadeos.api.app:create_app", factory=True, host="127.0.0.1", port=8765, workers=1, ws_max_size=40 * 1024 * 1024, timeout_keep_alive=5)


if __name__ == "__main__":
    main()
