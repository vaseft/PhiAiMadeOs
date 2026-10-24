"""Windows app-window launcher; use pythonw to keep the server console hidden."""
from __future__ import annotations

import ctypes
import http.cookiejar
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"


def probe():
    # Windows may report an HTTP connection timeout, rather than refusal, for
    # an unused loopback port. Check availability before the readiness request.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port:
        if os.name == "nt":
            port.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            port.bind(("127.0.0.1", 8765))
        except OSError:
            pass
        else:
            return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    try:
        with opener.open(URL + "/api/v1/session", timeout=2) as response:
            session = json.load(response)
        if not session.get("csrf_token"):
            raise RuntimeError("8765端口被其他服务占用，请先关闭冲突服务。")
        with opener.open(URL + "/api/v1/status", timeout=3) as response:
            service = json.load(response)
        if Path(service.get("root", "")).resolve() != ROOT:
            raise RuntimeError("8765端口上运行的是另一个目录的工作台，请先关闭该服务。")
        with opener.open(URL + "/api/v1/trainer", timeout=3) as response:
            status = json.load(response)
        if "can_start" not in status:
            raise RuntimeError("本地服务不是支持简洁训练窗口的版本。")
        return True
    except urllib.error.HTTPError as exc:
        raise RuntimeError("当前工作台服务版本不支持训练窗口，请先保存任务并重启工作台。") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, OSError) and getattr(exc.reason, "winerror", None) == 10061:
            return False
        if isinstance(exc.reason, ConnectionRefusedError):
            return False
        raise RuntimeError("本地服务暂时无法连接，请检查工作台是否正常启动。") from exc


def browser_path():
    for browser, product in (("msedge.exe", "Microsoft/Edge"), ("chrome.exe", "Google/Chrome")):
        for folder in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if folder:
                path = Path(folder) / product / "Application" / browser
                if path.is_file():
                    return path
    return None


def main():
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    process = None
    if not probe():
        python = ROOT / ".venv/Scripts/python.exe"
        if not python.is_file() or not (ROOT / "web/dist/trainer.html").is_file():
            raise RuntimeError("训练环境或界面未安装，请先运行 Install-PAMOs.cmd。")
        env = dict(os.environ, PAMOS_ROOT=str(ROOT), PYTHONUTF8="1", PYTHONUNBUFFERED="1")
        env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
        with (local / "trainer-server.stdout.log").open("ab") as stdout, (local / "trainer-server.stderr.log").open("ab") as stderr:
            process = subprocess.Popen([str(python), "-m", "phiaimadeos", "--root", str(ROOT)],
                cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        deadline = time.monotonic() + 45
        while not probe():
            if process.poll() is not None:
                # A simultaneous launcher may have acquired the singleton first.
                if probe():
                    break
                raise RuntimeError("训练服务启动失败，详情见 .local/trainer-server.stderr.log。")
            if time.monotonic() >= deadline:
                raise RuntimeError("服务启动超时，详情见 .local/trainer-server.stderr.log。")
            time.sleep(.3)
    browser = browser_path()
    page = URL + "/trainer.html"
    if browser:
        subprocess.Popen([str(browser), "--app=" + page, "--window-size=640,360", "--no-first-run"], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(page, new=1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, str(exc), "PAMOs 训练启动失败", 0x10)
        else:
            print(str(exc), file=sys.stderr)
        sys.exit(1)
