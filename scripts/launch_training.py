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
import traceback
import urllib.error
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"


class ServiceNotReady(RuntimeError):
    """A listener exists but has not completed a bounded readiness request."""


def port_in_use():
    # Windows may report an HTTP connection timeout, rather than refusal, for
    # an unused loopback port. Check availability before the readiness request.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as port:
        if os.name == "nt":
            port.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            port.bind(("127.0.0.1", 8765))
        except OSError:
            return True
        else:
            return False


def probe(timeout=2):
    if not port_in_use():
        return False
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def read_json(path):
        with opener.open(URL + path, timeout=timeout) as response:
            content = response.read(16385)
        if len(content) > 16384:
            raise RuntimeError("8765端口服务响应异常，请确认运行的是本目录的PAMOs工作台。")
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError("8765端口服务返回了无效内容，请检查端口冲突。") from exc
        if not isinstance(value, dict):
            raise RuntimeError("8765端口服务不是兼容的PAMOs工作台。")
        return value
    try:
        session = read_json("/api/v1/session")
        if not session.get("csrf_token"):
            raise RuntimeError("8765端口被其他服务占用，请先关闭冲突服务。")
        service = read_json("/api/v1/health")
        if not isinstance(service.get("root"), str) or not service["root"] or Path(service["root"]).resolve() != ROOT:
            raise RuntimeError("8765端口上运行的是另一个目录的工作台，请先关闭该服务。")
        if service.get("ready") is not True:
            raise ServiceNotReady("工作台正在初始化")
        if type(service.get("trainer_protocol")) is not int or service["trainer_protocol"] < 2 or service.get("features", {}).get("trainer_runtime") is not True:
            raise RuntimeError("当前服务版本尚未加载训练强度接口，请保存任务并重启PAMOs工作台。")
        return True
    except urllib.error.HTTPError as exc:
        if exc.code in (502, 503, 504):
            raise ServiceNotReady("工作台正在启动，请稍候") from exc
        raise RuntimeError("当前端口服务不支持新版训练窗口，请保存任务并重启PAMOs工作台；若仍失败，请检查端口冲突。") from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, OSError) and getattr(exc.reason, "winerror", None) == 10061:
            return False
        if isinstance(exc.reason, ConnectionRefusedError):
            return False
        raise ServiceNotReady("暂时无法连接本地工作台，正在等待") from exc
    except (TimeoutError, ConnectionError) as exc:
        raise ServiceNotReady("本地工作台暂未响应，正在等待") from exc


def browser_path():
    for browser, product in (("msedge.exe", "Microsoft/Edge"), ("chrome.exe", "Google/Chrome")):
        for folder in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
            if folder:
                path = Path(folder) / product / "Application" / browser
                if path.is_file():
                    return path
    return None


def ensure_service():
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    process = None
    deadline = time.monotonic() + 45
    while True:
        try:
            if probe(timeout=max(.1, min(2, (deadline - time.monotonic()) / 2))):
                return
        except ServiceNotReady:
            # A slow existing service is never mistaken for an absent service.
            pass
        if time.monotonic() >= deadline:
            raise RuntimeError("等待PAMOs工作台响应超时（45秒）。当前服务或其他程序可能繁忙；请检查 .local/trainer-server.stderr.log。训练断点不会被删除。")
        if process is not None and process.poll() is not None and not port_in_use():
            raise RuntimeError("训练服务启动失败，详情见 .local/trainer-server.stderr.log。")
        if process is None and not port_in_use():
            process = start_service(local)
        time.sleep(.3)


def start_service(local):
    python = ROOT / ".venv/Scripts/python.exe"
    if not python.is_file() or not (ROOT / "web/dist/trainer.html").is_file():
        raise RuntimeError("训练环境或界面未安装，请先运行 Install-PAMOs.cmd。")
    env = dict(os.environ, PAMOS_ROOT=str(ROOT), PYTHONUTF8="1", PYTHONUNBUFFERED="1")
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + str(ROOT)
    with (local / "trainer-server.stdout.log").open("ab") as stdout, (local / "trainer-server.stderr.log").open("ab") as stderr:
        return subprocess.Popen([str(python), "-m", "phiaimadeos", "--root", str(ROOT)],
            cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)


def main():
    ensure_service()
    browser = browser_path()
    page = URL + "/trainer.html"
    if browser:
        subprocess.Popen([str(browser), "--app=" + page, "--window-size=1100,660", "--no-first-run"], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        webbrowser.open(page, new=1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log = ROOT / ".local/trainer-launcher-error.log"
        try:
            log.parent.mkdir(exist_ok=True)
            with log.open("a", encoding="utf-8") as handle:
                handle.write(time.strftime("\n%Y-%m-%d %H:%M:%S\n") + traceback.format_exc())
        except OSError:
            pass
        message = str(exc) if isinstance(exc, RuntimeError) else "训练窗口启动遇到问题，详情见 .local/trainer-launcher-error.log。"
        if os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, message, "PAMOs 训练启动失败", 0x10)
        else:
            print(message, file=sys.stderr)
        sys.exit(1)
