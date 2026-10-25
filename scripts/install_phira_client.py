"""Prepare the official pinned client in .tools without launching or playtesting it."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import urllib.request
import zipfile


def main():
    root = Path(__file__).resolve().parents[1]
    client = json.loads((root / "configs/client-releases.lock.json").read_text(encoding="utf-8"))["phira_pro_windows"]
    archive_path = root / ".downloads" / client["asset"]
    tools = root / ".tools/Phira-Pro"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    tools.mkdir(parents=True, exist_ok=True)
    if not archive_path.exists():
        temporary = archive_path.with_suffix(".download")
        try:
            urllib.request.urlretrieve(client["url"], temporary)
            temporary.replace(archive_path)
        finally:
            temporary.unlink(missing_ok=True)
    with archive_path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != client["sha256"]:
        raise ValueError("官方客户端 SHA-256 不符，停止解压")
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > 2048 or sum(e.file_size for e in entries) > 512 * 1024 * 1024:
            raise ValueError("官方客户端归档超出安全限额")
        targets = set()
        for entry in entries:
            name = entry.filename
            parts = PurePosixPath(name).parts
            target = (tools / name).resolve()
            if "\\" in name or ":" in name or not parts or ".." in parts or PurePosixPath(name).is_absolute() or not target.is_relative_to(tools.resolve()):
                raise ValueError("归档包含不安全路径")
            if stat.S_ISLNK(entry.external_attr >> 16) or name.casefold() in targets:
                raise ValueError("归档包含软链接或重名路径")
            targets.add(name.casefold())
        executable = tools / "PhiraPro-v0.8.2-pro.16-win64/phira-main.exe"
        if executable.exists():
            print("已存在客户端，保留本机文件。")
        else:
            if any((tools / entry.filename).exists() for entry in entries if not entry.is_dir()):
                raise ValueError("本机已有部分客户端文件，为避免覆盖，请人工选择新的安装目录")
            archive.extractall(tools)
            print("官方 Windows 客户端哈希匹配并已解压；没有启动或试玩。")
    print(executable)


if __name__ == "__main__":
    main()
