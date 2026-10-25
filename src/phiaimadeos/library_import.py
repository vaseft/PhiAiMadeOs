"""Explicit local library import. No rights promotion, training, or external calls."""
from __future__ import annotations
from collections import Counter
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from .formats import (_preflight_zip, _archive_members, _bounded_read, _json, _info_yaml,
                      safe_member, canonical_bytes, chart_hash, chart_to_ir, MAX_JSON_BYTES, MAX_PACKAGE_BYTES)
from .settings import get_settings, atomic_json, file_hash, new_id, now
from .store import Store

AUDIO = {".wav", ".ogg", ".flac", ".mp3", ".m4a", ".aac"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp"}
RIGHTS = {"license_status": "unknown", "allowed_actions": ["local_research"]}


def _write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ValueError("导入目标已经存在，拒绝覆盖")
    fd, temporary = tempfile.mkstemp(prefix=".import-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _metadata(archive, members):
    for name in ("info.yml", "info.yaml"):
        if name in members:
            value = _info_yaml(_bounded_read(archive, members[name], 65536))
            # RPE switches such as useRpen/useRpe170Speed are case-sensitive.
            normalized = dict(value)
            folded = {}
            for key, item in value.items():
                alias = key.casefold()
                if alias in folded and folded[alias] != item:
                    raise ValueError("info.yml 含大小写冲突字段，不能猜测配置")
                folded[alias] = item
            for key in ("name", "level", "chart", "music", "illustration", "song", "picture", "offset"):
                if key in folded:
                    normalized.setdefault(key, folded[key])
            for old, new in (("song", "music"), ("picture", "illustration")):
                if old in normalized:
                    normalized.setdefault(new, normalized[old])
            return value, normalized
    if "info.txt" not in members:
        if "info.csv" not in members:
            return {}, {}
        text = _bounded_read(archive, members["info.csv"], 65536).decode("utf-8-sig")
        try:
            reader = csv.DictReader(io.StringIO(text, newline=""), strict=True)
            fields = reader.fieldnames or []
            if not fields or any(not field.strip() for field in fields) or len({field.casefold() for field in fields}) != len(fields):
                raise ValueError("info.csv 列名缺失或重复")
            rows = [row for row in reader if any(value for value in row.values())]
        except csv.Error as exc:
            raise ValueError("info.csv 格式无效") from exc
        if len(rows) != 1 or None in rows[0] or any(value is None for value in rows[0].values()):
            raise ValueError("info.csv 必须明确包含一条完整谱面记录，不能猜测多条配置")
        value = rows[0]
        folded = {key.casefold(): item for key, item in value.items()}
        normalized = dict(value)
        for old, new in (("chart", "chart"), ("music", "music"), ("image", "illustration"),
                         ("name", "name"), ("level", "level"), ("illustrator", "illustrator"), ("designer", "charter")):
            if old in folded:
                normalized[new] = folded[old]
        normalized["_pamos_metadata_format"] = "csv"
        return value, normalized
    text = _bounded_read(archive, members["info.txt"], 65536).decode("utf-8-sig")
    info = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lstrip("#").strip().lower()
        if key in info:
            raise ValueError("info.txt 包含重复字段，不能猜测资源关联")
        info[key] = value.strip()
    normalized = dict(info)
    for old, new in (("song", "music"), ("picture", "illustration")):
        if old in normalized and new not in normalized:
            normalized[new] = normalized[old]
    if "offset" in normalized:
        try:
            normalized["offset"] = float(normalized["offset"])
        except (TypeError, ValueError) as exc:
            raise ValueError("info.txt offset 不是有效秒数") from exc
    return info, normalized


def _resolve(members, reference, extensions, role, warnings, optional=False):
    if reference:
        if not isinstance(reference, str):
            raise ValueError(f"{role} 引用必须为字符串")
        # Unsafe references are never silently replaced by guessed assets.
        key = safe_member(reference).casefold()
        if key in members and not members[key].is_dir() and Path(key).suffix in extensions:
            return members[key]
        warnings.append(f"元数据 {role} 引用缺失/类型不符；按唯一实际文件恢复，原引用保留")
    choices = [item for item in members.values() if not item.is_dir() and PurePosixPath(item.filename).suffix.lower() in extensions
               and PurePosixPath(item.filename).name.lower() not in {"extra.json", "config.json"}]
    if len(choices) == 1:
        return choices[0]
    if optional and not choices:
        return None
    raise ValueError(f"{role} 无法唯一确定（实际候选 {len(choices)} 个），未猜测绑定")


def _labels(level, folder):
    text = str(level or folder)
    match = re.search(r"\b(EZ|HD|IN|AT)\b", text, re.I)
    category = match.group(1).upper() if match else None
    value_match = re.search(r"(?:Lv\.?\s*|\b(?:EZ|HD|IN|AT)\s+)(\d+(?:\.\d+)?)", text, re.I)
    number = float(value_match.group(1)) if value_match else None
    ranges = {"EZ": (0, 10), "HD": (11, 14), "IN": (14, 17), "AT": (15, 18)}
    training_value = None
    if category and number is not None and number.is_integer() and ranges[category][0] <= number <= ranges[category][1]:
        training_value = int(number)
    # A source category with no exact canonical value is not a complete model label.
    return {"source_level": text, "source_difficulty_class": category or folder, "source_difficulty_value": number,
            "difficulty_class": category if training_value is not None else None, "difficulty_value": training_value}


def _extract(archive, member, destination, maximum):
    if member.file_size > maximum:
        raise ValueError("包内素材超过导入限额")
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    count = 0
    created = False
    try:
        with archive.open(member) as source, destination.open("xb") as target:
            created = True
            while block := source.read(1024 * 1024):
                count += len(block)
                if count > maximum or count > member.file_size:
                    raise ValueError("实际展开体积超过登记值或限额")
                digest.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        if count != member.file_size:
            raise ValueError("素材展开体积不一致")
    except Exception:
        if created:
            destination.unlink(missing_ok=True)
        raise
    return digest.hexdigest(), count


def _backup_database(store, directory):
    target = directory / "database-before.sqlite3"
    with sqlite3.connect(store.settings.db_path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return target


def import_one(path, archive_sha, source_root, run_id, store, asset_index, expected_stat=None):
    from .audio import probe_audio
    settings = store.settings
    identifier = new_id()
    destination = settings.data_dir / "charts" / identifier
    warnings = []
    created_paths = []
    new_audio = None
    candidate = None
    source_stat = path.stat()
    if expected_stat is not None and (source_stat.st_size, source_stat.st_mtime_ns) != expected_stat:
        raise ValueError("包哈希读取后源文件已变化，未开始导入")
    if source_stat.st_size > MAX_PACKAGE_BYTES:
        raise ValueError("单个源包超过256 MiB限额")
    _preflight_zip(path)
    try:
        with zipfile.ZipFile(path) as archive:
            members = _archive_members(archive)
            raw_info, info = _metadata(archive, members)
            chart_member = _resolve(members, info.get("chart"), {".json", ".pec", ".pbc"}, "chart", warnings)
            music_member = _resolve(members, info.get("music"), AUDIO, "music", warnings, optional=True)
            image_member = _resolve(members, info.get("illustration"), IMAGES, "illustration", warnings, optional=True)
            labels = _labels(info.get("level"), path.parent.name)
            source_suffix = PurePosixPath(chart_member.filename).suffix.lower()
            source_path = destination / ("original" + source_suffix)
            # Keep the chart member bytes exactly as received, even if unsupported.
            raw_sha, _ = _extract(archive, chart_member, source_path, MAX_PACKAGE_BYTES)
            created_paths.append(source_path)
            source_format, chart, conversion_error = "unknown", None, None
            if source_suffix == ".json":
                try:
                    native = _json(source_path.read_bytes()) if source_path.stat().st_size <= MAX_JSON_BYTES else None
                    if native is None:
                        raise ValueError(f"原始 JSON 超过{MAX_JSON_BYTES // (1024 * 1024)} MiB有界解析限额，原件已存档")
                    if "formatVersion" in native:
                        source_format = "phigros_v" + str(native["formatVersion"])
                        if "line.csv" in members or info.get("_pamos_metadata_format") == "csv":
                            raise ValueError("外置 CSV 全局/判定线图片配置尚未映射；保留原件及资源，不生成省略演出的预览")
                        from .official import convert_official
                        chart = convert_official(native, info=info)
                    elif all(k in native for k in ("META", "BPMList", "judgeLineList")):
                        source_format = "rpe"
                        if "line.csv" in members or info.get("_pamos_metadata_format") == "csv":
                            raise ValueError("外置 CSV 全局/判定线图片配置尚未映射；保留原件及资源，不生成省略演出的预览")
                        chart = native
                        chart["_pamos_import"] = {"container": "zip", "info_format": "yaml", "info": info, "warnings": list(warnings)}
                    else:
                        raise ValueError("未识别 JSON 谱面方言")
                    ir = chart_to_ir(chart, "regular", None, copy_raw=False)
                    if len(canonical_bytes(chart)) > MAX_JSON_BYTES:
                        raise ValueError(f"转换后的共同 RPE 超过{MAX_JSON_BYTES // (1024 * 1024)} MiB，保留原件并报告资源限制")
                except (ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
                    chart, conversion_error = None, str(exc)
            else:
                source_format = source_suffix.lstrip(".")
                conversion_error = f"{source_format.upper()} 当前未实现转换；保留原谱与资源，未创建可预览候选"
            music_id = None
            if music_member:
                extension = PurePosixPath(music_member.filename).suffix.lower()
                temporary = settings.data_dir / "assets" / (".import-" + new_id() + extension)
                audio_sha, audio_size = _extract(archive, music_member, temporary, MAX_PACKAGE_BYTES)
                created_paths.append(temporary)
                known = asset_index.get(audio_sha)
                if known:
                    existing_path = settings.path(known["path"])
                    if not existing_path.is_file() or file_hash(existing_path) != audio_sha:
                        raise ValueError("已有音乐记录文件缺失或哈希变化，拒绝复用")
                    temporary.unlink()
                    created_paths.remove(temporary)
                    music_id = known["id"]
                else:
                    facts = probe_audio(temporary)
                    audio_path = settings.data_dir / "assets" / (audio_sha + extension)
                    if audio_path.exists():
                        if file_hash(audio_path) != audio_sha:
                            raise ValueError("同名本机音乐缓存哈希冲突")
                        temporary.unlink()
                    else:
                        temporary.replace(audio_path)
                        created_paths.append(audio_path)
                    created_paths.remove(temporary)
                    music_id = new_id()
                    new_audio = {"id": music_id, "name": str(info.get("name") or path.stem), "path": settings.relative(audio_path), "sha256": audio_sha, "size": audio_size,
                        "duration_s": facts["duration_s"], "sample_rate": facts["sample_rate"], "channels": facts["channels"], "analysis_path": None,
                        "source_type": "official", "source_claim": "user_supplied_official", "import_run_id": run_id, **RIGHTS}
            else:
                warnings.append("没有可唯一关联的音乐；只导入谱面")
            illustration_path = None
            if image_member:
                extension = PurePosixPath(image_member.filename).suffix.lower()
                image_path = destination / ("illustration" + extension)
                _extract(archive, image_member, image_path, 16 * 1024 * 1024)
                created_paths.append(image_path)
                illustration_path = settings.relative(image_path)
            if chart is not None:
                # Explicit audio duration overrides last-note duration for full-song playback.
                asset = new_audio or (asset_index.get(audio_sha) if music_id else None)
                if asset:
                    chart.setdefault("pamos", {})["duration_s"] = asset["duration_s"]
                warnings.extend(ir.get("warnings", []))
                warnings.extend(chart.get("pamos", {}).get("compatibility_limits", []))
                converted_path = destination / "chart.json"
                _write_new(converted_path, canonical_bytes(chart))
                created_paths.append(converted_path)
                stored_path = converted_path
                candidate_id = new_id()
                digest = chart_hash(chart)
                candidate = {"id": candidate_id, "music_asset_id": music_id, "chart_mode": "regular", "key_count": None,
                    "conditions": {"chart_mode": "regular", "key_count": None, "difficulty_class": labels["difficulty_class"], "difficulty_value": labels["difficulty_value"]},
                    "chart_path": settings.relative(converted_path), "chart_sha256": digest, "file_sha256": file_hash(converted_path), "status": "draft", "parent_id": None,
                    "audit_id": None, "source": "official_import", "manifest": {"source": "official_import", "chart_asset_id": identifier,
                        "source_format": source_format, "source_archive_sha256": archive_sha, "source_chart_sha256": raw_sha,
                        "import_run_id": run_id, "verification": "NOT RUN", "conversion_limits": chart.get("pamos", {}).get("compatibility_limits", [])}}
            else:
                stored_path, candidate_id = source_path, None
                warnings.append(conversion_error or "未能转换，原件只读保留")
            warnings.extend(["用户提供的官谱来源声明，未独立认证来源或许可", "未自动授权训练/分发；未自动确认对齐或试玩", "源小数难度及特殊难度保留，训练条件不自动舍入或映射"])
            extracted_names = {chart_member.filename, music_member.filename if music_member else None, image_member.filename if image_member else None}
            metadata_names = {"info.txt", "info.yml", "info.yaml", "info.csv"}
            retained_only = [item.filename for item in members.values() if not item.is_dir() and item.filename not in extracted_names and item.filename.lower() not in metadata_names]
            if retained_only:
                warnings.append("附加包内文件仍保留在未修改的原包，未打开或执行：" + ", ".join(retained_only[:12]))
            record = {"id": identifier, "name": str(info.get("name") or path.stem), "path": settings.relative(stored_path), "sha256": file_hash(stored_path),
                "original_path": settings.relative(source_path), "original_sha256": raw_sha, "source_archive_sha256": archive_sha,
                "source_archive_path": str(path.resolve()), "source_relative_path": path.relative_to(source_root).as_posix(), "source_chart_member": chart_member.filename,
                "source_music_member": music_member.filename if music_member else None, "source_info": raw_info, "source_members": [item.filename for item in members.values()], "retained_in_original_only": retained_only,
                "source_type": "official", "source_claim": "user_supplied_official",
                "source_format": source_format, "import_status": "ready" if chart is not None else "archived_only", "candidate_id": candidate_id,
                "music_asset_id": music_id, "illustration_path": illustration_path, "chart_mode": "regular", "key_count": None,
                "group_id": "audio-sha256:" + audio_sha if music_id else None, "group_method": "exact_audio_bytes_only", "human_verified_alignment": False,
                "warnings": list(dict.fromkeys(warnings)), "import_run_id": run_id, **labels, **RIGHTS}
        current = path.stat()
        if (current.st_size, current.st_mtime_ns) != (source_stat.st_size, source_stat.st_mtime_ns):
            raise ValueError("导入期间源包发生变化，未登记此次结果")
        entries = []
        if new_audio:
            entries.append(("assets", new_audio, False))
        entries.append(("charts", record, False))
        if candidate:
            entries.append(("candidates", candidate, False))
        store.put_many(entries)
        if new_audio:
            asset_index[new_audio["sha256"]] = new_audio
        return {"chart_id": identifier, "candidate_id": candidate_id, "music_asset_id": music_id, "new_audio": bool(new_audio), "source_format": source_format,
                "import_status": record["import_status"], "source_archive_sha256": archive_sha, "warning_count": len(record["warnings"]), "conversion_error": conversion_error}
    except Exception:
        # Only remove files that this invocation itself created under managed data.
        for created in reversed(created_paths):
            if created.is_file() and created.resolve().is_relative_to(settings.data_dir.resolve()):
                created.unlink(missing_ok=True)
        raise


def import_library(source, progress=None):
    store = Store()
    settings = store.settings
    source = Path(source).resolve(strict=True)
    if not source.is_dir():
        raise ValueError("谱面来源必须为用户明确指定的本机目录")
    packages = []
    for current, directories, files in os.walk(source, followlinks=False):
        directories[:] = [name for name in directories if not (Path(current) / name).is_symlink() and not (Path(current) / name).is_junction()]
        for name in files:
            path = Path(current) / name
            if path.suffix.lower() in {".zip", ".pez"} and not path.is_symlink():
                if not path.resolve().is_relative_to(source):
                    raise ValueError("来源目录包含越界的谱面路径")
                packages.append(path)
    packages.sort()
    if not packages:
        raise ValueError("来源目录没有 ZIP/PEZ 谱面包")
    if len(packages) > 5000:
        raise ValueError("单批谱面包最多5000个")
    if shutil.disk_usage(settings.data_dir).free < max(1024**3, sum(p.stat().st_size for p in packages) * 2):
        raise ValueError("剩余空间不足安全预留（源包总体积的2倍），请先释放空间")
    active = [j for j in store.list("jobs") if j.get("kind") == "library_import" and j["status"] in {"queued", "running", "cancelling"}]
    if active:
        raise ValueError("已有本地谱面库导入任务，请先等待或取消")
    run_id = new_id()
    directory = settings.data_dir / "imports" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    _backup_database(store, directory)
    job = store.put("jobs", {"id": run_id, "kind": "library_import", "request": {"source_path": str(source)}, "status": "running", "progress": 0,
        "message": f"准备导入{len(packages)}个本机谱面包", "started_at": now(), "result": None, "error": None})
    report = {"id": run_id, "created_at": now(), "source_path": str(source), "total_packages": len(packages), "permission": RIGHTS,
        "source_unchanged": True, "tests": "NOT RUN", "training": "NOT RUN", "client_playtest": "NOT RUN", "items": []}
    existing = {r.get("source_archive_sha256"): r for r in store.list("charts") if r.get("source_archive_sha256")}
    assets = {r["sha256"]: r for r in store.list("assets")}
    counts = Counter()
    started = time.monotonic()
    try:
        for index, path in enumerate(packages):
            if store.get("jobs", run_id)["status"] != "running":
                break
            item = {"source_relative_path": path.relative_to(source).as_posix()}
            try:
                before = path.stat()
                archive_sha = file_hash(path)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError("源包仍在下载/修改，请稍后重试")
                if archive_sha in existing:
                    result = {"import_status": "duplicate", "chart_id": existing[archive_sha]["id"], "source_archive_sha256": archive_sha}
                else:
                    result = import_one(path, archive_sha, source, run_id, store, assets, (after.st_size, after.st_mtime_ns))
                    existing[archive_sha] = result | {"id": result["chart_id"]}
                item.update(result)
                counts[result["import_status"]] += 1
                counts["new_audio"] += int(result.get("new_audio", False))
            except (OSError, ValueError, zipfile.BadZipFile, KeyError, TypeError, UnicodeError) as exc:
                item.update(import_status="failed", error=str(exc)[:2000])
                counts["failed"] += 1
            report["items"].append(item)
            summary = {"total": len(packages), "processed": index + 1, **dict(counts)}
            store.update("jobs", run_id, {"progress": (index + 1) / len(packages), "message": f"已处理{index+1}/{len(packages)}；可预览{counts['ready']}，仅存档{counts['archived_only']}，失败{counts['failed']}", "result": summary})
            if progress and ((index + 1) % 10 == 0 or index + 1 == len(packages)):
                progress(summary)
            if (index + 1) % 10 == 0:
                atomic_json(directory / "report.json", report)
        report.update(counts=dict(counts), processed=len(report["items"]), finished_at=now(), elapsed_s=round(time.monotonic()-started, 2))
        atomic_json(directory / "report.json", report)
        state = store.get("jobs", run_id)["status"]
        if state == "running":
            state = "succeeded" if not counts["failed"] else "partial"
        elif state == "cancelling":
            state = "cancelled"
        store.update("jobs", run_id, {"status": state, "finished_at": now(), "result": {"import_run_id": run_id, "total": len(packages), "processed": len(report["items"]), **dict(counts), "report_path": settings.relative(directory / "report.json")}, "message": "本地导入处理结束；许可、对齐和试玩仍需独立确认"})
        store.event("library.imported", run_id, counts=dict(counts), source_files_modified=False)
        return report
    except BaseException as exc:
        report.update(error=str(exc)[:2000], counts=dict(counts), finished_at=now())
        atomic_json(directory / "report.json", report)
        store.update("jobs", run_id, {"status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", "error": str(exc)[:1000], "finished_at": now(), "message": "导入中断；已登记的完整包保留，可重跑去重继续"})
        raise
