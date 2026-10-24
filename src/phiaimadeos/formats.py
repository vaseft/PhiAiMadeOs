"""Independent common-RPE adapter; unknown source fields remain in the raw layer.

Client contract: Phira-Pro 4ed6aaf6, prpr/src/parse/rpe.rs and scene/game.rs.
This module does not certify either editor dialect or client playability.
"""
from __future__ import annotations

import copy
from bisect import bisect_right
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zipfile
import zlib

PARSER_VERSION = "common-rpe-1.0.0"
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_PACKAGE_BYTES = 256 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_ENTRIES = 512
MAX_NOTES = 300_000
MAX_LINES = 512
KINDS = {1: "TAP", 2: "HOLD", 3: "FLICK", 4: "DRAG"}
NOISE_KEYS = {"noisearea", "noisearealayers", "noiseareaoptions", "blockarealist", "noise_area", "noiseareas"}


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def chart_hash(chart):
    payload = {k: v for k, v in chart.items() if k != "_pamos_import"}
    # Package metadata can change the judgement clock and parser flags. Bind the
    # full info object; importer bookkeeping/source filenames remain nonsemantic.
    imported = chart.get("_pamos_import", {})
    info_offset = imported.get("info", {}).get("offset", 0) if imported.get("info_format") != "rpe_text" else 0
    _finite(info_offset, "info.offset")
    info = imported.get("info", {})
    if info:
        payload = {"chart": payload, "package_info": info, "info_format": imported.get("info_format")}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _finite(value, name="number"):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} 必须是有限数值")
    return value


def _check_tree(value, depth=0, count=None):
    count = [0] if count is None else count
    count[0] += 1
    if depth > 64 or count[0] > 2_000_000:
        raise ValueError("JSON 嵌套或节点数量超过安全限额")
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise ValueError("JSON 对象键必须是字符串")
            _check_tree(v, depth + 1, count)
    elif isinstance(value, list):
        for v in value:
            _check_tree(v, depth + 1, count)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("不允许 NaN 或 Infinity")
    elif value is not None and not isinstance(value, (str, bool, int, float)):
        raise ValueError("只允许 JSON 基本类型")


def _json(data):
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("谱面 JSON 超过 32 MiB 限额")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"JSON 含重复键: {key}")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs,
                           parse_constant=lambda s: (_ for _ in ()).throw(ValueError(f"非法数值 {s}")))
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("谱面不是有效 UTF-8 JSON") from exc
    _check_tree(value)
    if not isinstance(value, dict):
        raise ValueError("谱面根节点必须为对象")
    return value


def safe_member(name):
    """Use the same conservative path policy on every host, including Windows."""
    if not isinstance(name, str) or not name or len(name) > 240 or "\\" in name or "\x00" in name:
        raise ValueError("包内路径无效")
    p = PurePosixPath(name)
    if p.is_absolute() or any(s in {"", ".", ".."} for s in name.rstrip("/").split("/")):
        raise ValueError("拒绝包内路径穿越")
    for part in p.parts:
        if any(ord(c) < 32 or c in '<>:"|?*' for c in part) or part.endswith((" ", ".")):
            raise ValueError("包内路径不符合跨平台安全约束")
        if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", part, re.I):
            raise ValueError("包内路径使用 Windows 保留名")
    return p.as_posix()


def _archive_members(archive):
    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        raise ValueError("包内条目超过 512 个")
    members, total = {}, 0
    for item in infos:
        name = safe_member(item.filename)
        mode = (item.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode) or (mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError("拒绝符号链接或特殊文件")
        if item.flag_bits & 1:
            raise ValueError("不支持加密 ZIP")
        if item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ValueError("不支持此 ZIP 压缩方式")
        key = name.casefold().rstrip("/")
        if key in members:
            raise ValueError("包内存在重复或大小写冲突的文件名")
        total += item.file_size
        if item.file_size > MAX_PACKAGE_BYTES or total > MAX_EXPANDED_BYTES:
            raise ValueError("包内展开体积超过安全限额")
        if item.file_size > 1024 * 1024 and item.file_size / max(1, item.compress_size) > 250:
            raise ValueError("压缩比超过安全限额")
        members[key] = item
    # A file and a directory at the same prefix are ambiguous on extraction.
    for key, item in members.items():
        for parent in PurePosixPath(key).parents:
            if str(parent) in members and not members[str(parent)].is_dir():
                raise ValueError("包内路径前缀与文件冲突")
    return members


def _bounded_read(archive, member, maximum):
    if member.file_size > maximum:
        raise ValueError("包内文件超过读取限额")
    with archive.open(member) as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum or len(data) != member.file_size:
        raise ValueError("包内文件实际体积无效")
    return data


def _preflight_zip(path):
    # Bound the central directory before zipfile constructs a ZipInfo for every
    # entry. ZIP64/multidisk archives have no role within these small limits.
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - 65557))
        tail = stream.read(65557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or len(tail) - position < 22:
        raise ValueError("ZIP 缺少有效中央目录")
    _, disk, central_disk, disk_entries, entries, directory_size, directory_offset, comment = struct.unpack("<4s4H2IH", tail[position:position + 22])
    if position + 22 + comment != len(tail) or disk or central_disk or disk_entries != entries:
        raise ValueError("不支持多卷或损坏的 ZIP")
    if entries > MAX_ENTRIES or directory_size > 4 * 1024 * 1024 or directory_offset + directory_size > size:
        raise ValueError("ZIP 中央目录超过安全限额或使用不支持的 ZIP64")


def _info_yaml(data):
    import yaml
    # Reject aliases/tags before constructing anything; metadata has no need for them.
    for token in yaml.scan(data.decode("utf-8-sig")):
        if isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken, yaml.tokens.TagToken)):
            raise ValueError("info.yml 不允许 YAML 引用或标签")
    class UniqueLoader(yaml.SafeLoader):
        pass
    def unique_mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("info.yml 含非字符串键或重复键")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)
    info = yaml.load(data, Loader=UniqueLoader) or {}
    if not isinstance(info, dict):
        raise ValueError("info.yml 必须是对象")
    _check_tree(info)
    return info


def read_chart(path):
    path = Path(path)
    limit = MAX_PACKAGE_BYTES if path.suffix.lower() in {".pez", ".zip"} else MAX_JSON_BYTES
    if path.stat().st_size > limit:
        raise ValueError("输入文件超过安全体积限额")
    if path.suffix.lower() == ".json":
        value = _json(path.read_bytes())
        imported = {"container": "json", "warnings": []}
    elif path.suffix.lower() in {".zip", ".pez"}:
        _preflight_zip(path)
        with zipfile.ZipFile(path) as archive:
            members = _archive_members(archive)
            info, reference, info_format = {}, None, None
            if "info.yml" in members or "info.yaml" in members:
                member = members.get("info.yml", members.get("info.yaml"))
                info = _info_yaml(_bounded_read(archive, member, 64 * 1024))
                info_format = "yaml"
                reference = info.get("chart")
            elif "info.txt" in members:
                data = _bounded_read(archive, members["info.txt"], 64 * 1024).decode("utf-8-sig")
                info = {k.strip().lstrip("#").strip().lower(): v.strip() for line in data.splitlines()
                        if ":" in line for k, v in [line.split(":", 1)]}
                info_format = "rpe_text"
                reference = info.get("chart")
            if reference:
                safe_member(reference)
                member = members.get(reference.casefold())
                if member is None or member.is_dir():
                    raise ValueError("info 引用的谱面文件不存在")
            else:
                candidates = []
                for item in members.values():
                    if item.is_dir() or not item.filename.lower().endswith(".json") or item.file_size > MAX_JSON_BYTES:
                        continue
                    if PurePosixPath(item.filename).name.lower() in {"extra.json", "config.json"}:
                        continue
                    candidate = _json(_bounded_read(archive, item, MAX_JSON_BYTES))
                    if "BPMList" in candidate and "judgeLineList" in candidate:
                        candidates.append(item)
                if len(candidates) != 1:
                    raise ValueError("包内未找到唯一共同 RPE 谱面；请提供有效 info.chart")
                member = candidates[0]
            if not member.filename.lower().endswith(".json"):
                raise ValueError("当前只支持共同 RPE JSON，不支持 PEC/PBC/官谱转换")
            value = _json(_bounded_read(archive, member, MAX_JSON_BYTES))
            warnings = ["包内媒体仅登记引用；没有提取或导入音频、曲绘及附加资源"]
            recognized = {".json", ".yml", ".yaml", ".txt", ".ogg", ".mp3", ".wav", ".flac", ".m4a", ".aac",
                          ".png", ".jpg", ".jpeg", ".webp", ".gif", ".glsl", ".frag", ".vert"}
            unsupported_members = [item.filename for item in members.values()
                                   if not item.is_dir() and PurePosixPath(item.filename).suffix.lower() not in recognized]
            if unsupported_members:
                warnings.append("未识别的包内文件未打开或执行：" + ", ".join(unsupported_members[:12]))
            for field in ("music", "illustration"):
                if info.get(field):
                    safe_member(info[field])
                    if info[field].casefold() not in members:
                        raise ValueError(f"info.{field} 引用的资源不存在")
            imported = {"container": path.suffix.lower()[1:], "chart_member": member.filename,
                        "info": info, "info_format": info_format,
                        "members": [v.filename for v in members.values()], "unsupported_members": unsupported_members,
                        "warnings": warnings}
    else:
        raise ValueError("仅支持 .json/.pez/.zip 的共同 RPE 结构")
    if "_pamos_import" in value:
        if path.suffix.lower() != ".json":
            raise ValueError("外部包内谱面含保留内部字段 _pamos_import")
        previous = value.pop("_pamos_import")
        if not isinstance(previous, dict) or not isinstance(previous.get("info", {}), dict):
            raise ValueError("内部导入元数据结构无效")
        if previous.get("info_format") != "rpe_text":
            _finite(previous.get("info", {}).get("offset", 0), "内部 info.offset")
        if not isinstance(previous.get("warnings", []), list) or not all(isinstance(v, str) for v in previous.get("warnings", [])):
            raise ValueError("内部导入 warnings 必须是字符串数组")
        # Standardized local snapshots retain their effective package offset.
        # Nothing here grants rights, approval or trusted-source status.
        imported = copy.deepcopy(previous)
        imported["normalized_snapshot"] = True
    if not all(key in value for key in ("BPMList", "META", "judgeLineList")):
        raise ValueError("不支持此谱面方言；需要 BPMList/META/judgeLineList")
    imported["source_sha256"] = _file_hash(path)
    imported["parser_version"] = PARSER_VERSION
    value["_pamos_import"] = imported
    return value


def _file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def beat_fraction(beat):
    if isinstance(beat, Fraction):
        return beat
    if isinstance(beat, (list, tuple)) and len(beat) == 3:
        whole, numerator, denominator = beat
        if any(isinstance(v, bool) or not isinstance(v, int) for v in beat) or denominator <= 0:
            raise ValueError("拍数必须是整数三元组且分母为正")
        return Fraction(whole) + Fraction(numerator, denominator)
    if isinstance(beat, dict):
        return Fraction(beat["numerator"], beat["denominator"])
    if isinstance(beat, int) and not isinstance(beat, bool):
        return Fraction(beat)
    if isinstance(beat, float) and math.isfinite(beat):
        return Fraction(str(beat))
    raise ValueError("无效拍数")


def beat_triplet(beat):
    value = beat_fraction(beat)
    whole = value.numerator // value.denominator
    remainder = value - whole
    return [whole, remainder.numerator, remainder.denominator]


def _bpm_segments(bpm_map):
    if not isinstance(bpm_map, list) or not 1 <= len(bpm_map) <= 10000:
        raise ValueError("BPM 表必须包含 1..10000 段")
    segments = []
    for item in bpm_map:
        if not isinstance(item, dict):
            raise ValueError("BPM 段必须为对象")
        start = beat_fraction(item.get("startTime", item.get("start_beat", item.get("beat"))))
        bpm = _finite(item["bpm"], "BPM")
        if not 0 < bpm <= 10000:
            raise ValueError("BPM 必须在 (0,10000] 范围")
        if segments and start <= segments[-1][0]:
            raise ValueError("BPM 边界必须严格递增")
        segments.append((start, Fraction(str(bpm))))
    if segments[0][0] > 0:
        raise ValueError("BPM 表必须覆盖第0拍")
    return segments


class _TempoMap:
    """Exact segment integration, logarithmic lookups for large imported charts."""
    def __init__(self, bpm_map):
        segments = _bpm_segments(bpm_map)
        self.starts = [segment[0] for segment in segments]
        self.bpms = [segment[1] for segment in segments]
        self.times = [Fraction(0)]
        for index in range(1, len(segments)):
            self.times.append(self.times[-1] + (self.starts[index] - self.starts[index - 1]) * 60 / self.bpms[index - 1])
        self.zero = self._primitive(Fraction(0))

    def _primitive(self, beat):
        index = max(0, bisect_right(self.starts, beat) - 1)
        return self.times[index] + (beat - self.starts[index]) * 60 / self.bpms[index]

    def to_seconds(self, beat):
        return float(self._primitive(beat_fraction(beat)) - self.zero)

    def to_beat(self, seconds):
        _finite(seconds, "秒数")
        target = Fraction(str(seconds)) + self.zero
        index = max(0, bisect_right(self.times, target) - 1)
        result = self.starts[index] + (target - self.times[index]) * self.bpms[index] / 60
        # Seconds are derived/inexact; imported beat triplets never use this limit.
        return beat_triplet(result.limit_denominator(1_000_000))


def beat_to_seconds(beat, bpm_map):
    return _TempoMap(bpm_map).to_seconds(beat)


def seconds_to_beat(seconds, bpm_map):
    return _TempoMap(bpm_map).to_beat(seconds)


def noise_snapshot(value, path=""):
    found = {}
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = path + "/" + key
            if key.lower().replace("_", "") in {v.replace("_", "") for v in NOISE_KEYS}:
                found[child_path] = copy.deepcopy(child)
            else:
                found.update(noise_snapshot(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.update(noise_snapshot(child, path + "/" + str(index)))
    return found


def has_noise(value):
    """Empty layer definitions/options are retained but are not active areas."""
    for path, child in noise_snapshot(value).items():
        key = path.rsplit("/", 1)[-1].lower().replace("_", "")
        if key == "noiseareaoptions":
            continue
        if key == "noisearealayers":
            if isinstance(child, list) and any(has_noise(layer) for layer in child):
                return True
            continue
        if child:
            return True
    return False


def has_nontrivial_controls(line):
    for name, prop, neutral in (("posControl", "pos", 1), ("yControl", "y", 1), ("skewControl", "skew", 0),
                                ("sizeControl", "size", 1), ("alphaControl", "alpha", 1)):
        events = line.get(name) or []
        if not isinstance(events, list):
            return True
        if any(not isinstance(event, dict) or event.get(prop, neutral) != neutral for event in events):
            return True
    return False


def has_extended_features(line):
    extended = line.get("extended")
    if extended is None:
        return False
    if not isinstance(extended, dict):
        return True
    return any(bool(value) for value in extended.values())


def lane_centers(key_count):
    if key_count not in (4, 5, 6):
        raise ValueError("纯配置 key_count 必须为 4、5 或 6")
    return [675.0 * (-1 + 2 * (i + 0.5) / key_count) for i in range(key_count)]


def chart_to_ir(chart, chart_mode="regular", key_count=None):
    _check_tree(chart)
    if chart_mode not in {"regular", "pure_keys", "anomaly"}:
        raise ValueError("未知 chart_mode")
    if chart_mode == "pure_keys":
        lane_centers(key_count)
    elif key_count is not None:
        raise ValueError("常规/异像模式 key_count 必须为空")
    raw = copy.deepcopy({k: v for k, v in chart.items() if k != "_pamos_import"})
    if not all(k in raw for k in ("BPMList", "META", "judgeLineList")):
        raise ValueError("仅支持共同 RPE JSON 结构")
    bpm_map = copy.deepcopy(raw["BPMList"])
    tempo = _TempoMap(bpm_map)
    for segment in bpm_map:
        if not isinstance(segment.get("startTime"), list) or len(segment["startTime"]) != 3:
            raise ValueError("RPE BPMList.startTime 必须是三元数组")
    lines = raw["judgeLineList"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValueError("判定线数量必须在 1..512 内")
    meta = raw["META"]
    if not isinstance(meta, dict):
        raise ValueError("META 必须是对象")
    offset = _finite(meta.get("offset", 0), "META.offset")
    imported = chart.get("_pamos_import", {})
    info_offset = (_finite(imported.get("info", {}).get("offset", 0), "info.offset")
                   if imported.get("info_format") != "rpe_text" else 0)
    warnings = list(imported.get("warnings", []))
    unsupported = []
    for name in ("shaders", "effects", "extra", "assets", "shaderList"):
        if raw.get(name):
            unsupported.append(f"root.{name}: 扩展素材/效果仅 raw 保留")
    notes, judge_lines = [], []
    for index, line in enumerate(lines):
        if not isinstance(line, dict):
            raise ValueError("判定线必须是对象")
        parent = line.get("father", -1)
        if parent is None:
            parent = -1
        if isinstance(parent, bool) or not isinstance(parent, int) or parent < -1 or parent >= len(lines):
            raise ValueError("父判定线索引无效")
        factor = _finite(line.get("bpmfactor", 1), "bpmfactor")
        if factor <= 0:
            raise ValueError("bpmfactor 必须为正")
        use_rpen = imported.get("info", {}).get("useRpen") is not False
        time_scale = factor if use_rpen else 1
        judge_lines.append({"id": f"line_{index}", "parent_id": None if parent == -1 else f"line_{parent}",
                            "time_scale": time_scale, "raw": copy.deepcopy(line)})
        if factor != 1:
            warnings.append(f"line_{index}: bpmfactor={factor}，按包 useRpen 标志生效 time_scale={time_scale}；客户端试听 NOT RUN")
        if line.get("attachUI") not in (None, "", False) or line.get("Texture", "line.png") != "line.png" or has_extended_features(line):
            unsupported.append(f"line_{index}: 自定义纹理/UI/扩展事件仅 raw 保留，几何求值范围有限")
        if has_nontrivial_controls(line):
            unsupported.append(f"line_{index}: 非中性控制曲线只读保留，未完整复现判定几何")
        for layer in line.get("eventLayers", []) if isinstance(line.get("eventLayers", []), list) else []:
            if not isinstance(layer, dict):
                continue
            for track in layer.values():
                if isinstance(track, list) and any(isinstance(event, dict) and any("trajectory" in k.lower() or k.lower().startswith("path") for k in event) for event in track):
                    unsupported.append(f"line_{index}: Next 整体轨迹仅 raw 保留，不能静默转成标量事件")
        line_notes = line.get("notes") or []
        if not isinstance(line_notes, list):
            raise ValueError("notes 必须为数组或 null")
        for ni, note in enumerate(line_notes):
            if not isinstance(note, dict):
                raise ValueError("音符必须是对象")
            if len(notes) >= MAX_NOTES:
                raise ValueError("音符数量超过安全限额")
            if isinstance(note.get("type"), bool) or not isinstance(note.get("type"), int):
                raise ValueError("音符 type 必须为整数")
            kind = KINDS.get(note.get("type"))
            if kind is None:
                raise ValueError("不支持未知音符类型；拒绝静默丢弃")
            beat = beat_triplet(note["startTime"])
            end = beat_triplet(note.get("endTime", beat))
            if not isinstance(note.get("startTime"), list) or ("endTime" in note and not isinstance(note["endTime"], list)):
                raise ValueError("RPE 音符 startTime/endTime 必须是三元数组")
            x = _finite(note.get("positionX", 0), "positionX")
            if not isinstance(note.get("isFake", 0), (int, bool)) or not 0 <= note.get("isFake", 0) <= 255:
                raise ValueError("isFake 必须是0..255整数或布尔值")
            lane_index = note.get("pamosLaneIndex")
            lane_provenance = {"source": "explicit" if lane_index is not None else "unknown", "position_error": None}
            if chart_mode == "pure_keys" and lane_index is None:
                centers = lane_centers(key_count)
                distances = [abs(x - center) for center in centers]
                nearest = min(range(key_count), key=distances.__getitem__)
                if distances[nearest] <= 1e-4:
                    lane_index = nearest
                    lane_provenance = {"source": "computed_canonical_column", "position_error": distances[nearest],
                                       "method_version": PARSER_VERSION}
                else:
                    warnings.append(f"line_{index}/note_{ni}: 缺少经确认的固定列标签，未自动吸附")
            if any(note.get(name) is not None for name in ("tint", "tintHitEffects", "judgeArea", "hitsound")):
                unsupported.append(f"line_{index}: 音符颜色/判定范围/自定义音效仅 raw 保留")
            notes.append({"id": str(note.get("pamosId", f"note_{index}_{ni}")), "line_id": f"line_{index}",
                          "kind": kind, "beat": beat, "end_beat": end,
                          "time_s": tempo.to_seconds(beat) * time_scale + offset / 1000 + info_offset,
                          "end_time_s": tempo.to_seconds(end) * time_scale + offset / 1000 + info_offset,
                          "x": x, "above": note.get("above", 1), "fake": bool(note.get("isFake", 0)),
                          "lane_index": lane_index, "lane_provenance": lane_provenance, "raw": copy.deepcopy(note)})
    noise = noise_snapshot(raw)
    if has_noise(raw):
        warnings.append("包含噪域：只读保留，禁止生成、训练或自动修改；噪域几何未认证")
        unsupported.append("noise_area_read_only")
    generation = raw.get("pamos", {})
    if not isinstance(generation, dict):
        raise ValueError("pamos 元数据必须是对象")
    duration = generation.get("duration_s", max(0, max((n["end_time_s"] for n in notes), default=0)))
    _finite(duration, "duration_s")
    if duration < 0:
        raise ValueError("duration_s 不能为负")
    return {"schema_version": "1.0.0", "chart_mode": chart_mode, "key_count": key_count,
            "bpm_map": bpm_map, "offset_ms": offset, "info_offset_s": info_offset, "duration_s": duration,
            "notes": notes, "judge_lines": judge_lines, "raw_payload": raw, "warnings": warnings,
            "import_metadata": copy.deepcopy(imported),
            "unsupported_features": list(dict.fromkeys(unsupported)),
            "noise_sha256": hashlib.sha256(canonical_bytes(noise)).hexdigest(),
            "time_mapping": {"mapping_version": "phira-pro-4ed6aaf-source", "audio_minus_chart_seconds": offset / 1000 + info_offset,
                             "verified_against_client": False, "source_verified": True,
                             "playtest_status": "NOT RUN", "source_fields": {"META.offset": offset, "info.offset": info_offset}}}


def ir_to_chart(ir):
    chart = copy.deepcopy(ir.get("raw_payload", {}))
    if not chart:
        raise ValueError("IR 缺少 raw_payload；请使用 make_chart 创建新谱面")
    actual_noise = hashlib.sha256(canonical_bytes(noise_snapshot(chart))).hexdigest()
    if noise_snapshot(chart) and "noise_sha256" not in ir:
        raise ValueError("含噪域原字段的 IR 缺少只读指纹")
    if actual_noise != ir.get("noise_sha256", actual_noise):
        raise ValueError("噪域只读指纹不匹配")
    lines = ir["judge_lines"]
    ids = {line["id"]: index for index, line in enumerate(lines)}
    if len(ids) != len(lines):
        raise ValueError("判定线 ID 重复")
    result_lines = []
    for line in lines:
        raw = copy.deepcopy(line.get("raw", {}))
        parent = line.get("parent_id")
        if parent is not None and parent not in ids:
            raise ValueError("父判定线引用不存在")
        raw["father"] = -1 if parent is None else ids[parent]
        raw["notes"] = []
        result_lines.append(raw)
    reverse = {value: key for key, value in KINDS.items()}
    for note in ir["notes"]:
        if note["line_id"] not in ids:
            raise ValueError("音符所属判定线不存在")
        raw = copy.deepcopy(note.get("raw", {}))
        original_fake = raw.get("isFake", 0)
        exported_fake = original_fake if bool(original_fake) == bool(note["fake"]) else int(note["fake"])
        raw.update({"type": reverse[note["kind"].upper()], "startTime": beat_triplet(note["beat"]),
                    "endTime": beat_triplet(note.get("end_beat", note["beat"])), "positionX": _finite(note["x"]),
                    "above": note["above"], "isFake": exported_fake})
        if note.get("lane_index") is not None:
            raw["pamosLaneIndex"] = note["lane_index"]
        result_lines[ids[note["line_id"]]]["notes"].append(raw)
    chart["judgeLineList"] = result_lines
    chart["BPMList"] = copy.deepcopy(ir["bpm_map"])
    chart.setdefault("META", {})["offset"] = _finite(ir.get("offset_ms", 0))
    if noise_snapshot(chart) != noise_snapshot(ir.get("raw_payload", {})):
        raise ValueError("转换会修改噪域，已拒绝")
    _check_tree(chart)
    imported = copy.deepcopy(ir.get("import_metadata", {}))
    if imported or ir.get("info_offset_s", 0):
        imported.setdefault("container", "zip")
        imported.setdefault("warnings", [])
        if imported.get("info_format") != "rpe_text":
            imported.setdefault("info", {})["offset"] = ir.get("info_offset_s", 0)
        chart["_pamos_import"] = imported
    return chart


def _event(start, end, value, final=None):
    return {"startTime": beat_triplet(start), "endTime": beat_triplet(end), "start": value,
            "end": value if final is None else final, "easingType": 1, "easingLeft": 0.0,
            "easingRight": 1.0, "bezier": 0, "bezierPoints": [0, 0, 1, 1], "linkgroup": 0}


def make_chart(notes, bpm, duration_s, conditions):
    bpm = _finite(bpm, "BPM")
    _bpm_segments([{"bpm": bpm, "startTime": [0, 0, 1]}])
    duration_s = _finite(duration_s, "时长")
    if not 0 < duration_s <= 7200:
        raise ValueError("生成时长须在 (0,7200] 秒")
    mode = conditions.get("chart_mode", "regular")
    key_count = conditions.get("key_count")
    if mode not in {"regular", "pure_keys", "anomaly"}:
        raise ValueError("未知模式")
    if conditions.get("special_features"):
        raise ValueError("规则/RPE 基础适配器尚未认证特殊机制，不能生成")
    if mode == "pure_keys":
        centers = lane_centers(key_count)
    elif key_count is not None:
        raise ValueError("非纯配置模式 key_count 必须为空")
    bpm_map = [{"bpm": bpm, "startTime": [0, 0, 1]}]
    tempo = _TempoMap(bpm_map)
    finish = tempo.to_beat(duration_s + 4)
    def normalized_line_id(value):
        return f"line_{value}" if isinstance(value, int) and not isinstance(value, bool) else str(value)
    line_ids = list(dict.fromkeys(normalized_line_id(n.get("line_id", "line_0")) for n in notes)) or ["line_0"]
    if all(re.fullmatch(r"line_\d+", value) for value in line_ids):
        highest = max(int(value.split("_")[-1]) for value in line_ids)
        if highest >= MAX_LINES:
            raise ValueError("生成判定线索引超出安全范围")
        line_ids = [f"line_{index}" for index in range(highest + 1)]
    if mode == "pure_keys":
        line_ids = ["line_0"]
    if len(line_ids) > MAX_LINES or len(notes) > MAX_NOTES:
        raise ValueError("生成数量超过安全限额")
    lines = []
    for index, _ in enumerate(line_ids):
        lines.append({"Name": f"PAMOs {index + 1}", "Texture": "line.png", "father": -1,
                      "bpmfactor": 1.0, "isCover": 1, "zOrder": index, "Group": 0,
                      "notes": [], "eventLayers": [{"moveXEvents": [_event(0, finish, 0)],
                          "moveYEvents": [_event(0, finish, -202.5 if mode == "pure_keys" else 0)],
                          "rotateEvents": [_event(0, finish, 0)], "alphaEvents": [_event(0, finish, 255)],
                          "speedEvents": [_event(0, finish, 6.0)]}], "extended": {},
                      "alphaControl": [], "posControl": [], "sizeControl": [], "skewControl": [], "yControl": []})
    for index, source in enumerate(notes):
        kind = str(source.get("kind", "TAP")).upper()
        reverse = {value: key for key, value in KINDS.items()}
        if kind not in reverse:
            raise ValueError("未知生成音符类型")
        start_s = _finite(source["time_s"], "time_s")
        end_s = _finite(source.get("end_time_s", start_s), "end_time_s")
        if start_s < 0 or end_s > duration_s + 1e-6 or end_s < start_s or (kind == "HOLD" and end_s <= start_s):
            raise ValueError("生成音符时间超出范围或 Hold 无长度")
        lane = source.get("lane_index")
        x = _finite(source.get("x", 0), "x")
        if mode == "pure_keys":
            if isinstance(lane, bool) or not isinstance(lane, int) or not 0 <= lane < key_count:
                raise ValueError("纯配置音符缺少合法 lane_index")
            x = centers[lane]
        ni = {"type": reverse[kind], "startTime": tempo.to_beat(start_s),
              "endTime": tempo.to_beat(end_s if kind == "HOLD" else start_s),
              "positionX": x, "above": source.get("above", 1), "isFake": int(source.get("fake", False)),
              "alpha": 255, "size": 1, "speed": 1, "visibleTime": 999999, "yOffset": 0,
              "pamosId": str(source.get("id", f"note_{index}"))}
        if mode == "pure_keys":
            ni["pamosLaneIndex"] = lane
        lines[0 if mode == "pure_keys" else line_ids.index(normalized_line_id(source.get("line_id", "line_0")))]["notes"].append(ni)
    return {"BPMList": bpm_map, "META": {"RPEVersion": 170, "offset": 0, "name": "PAMOs candidate",
            "composer": "", "charter": "PhiAiMadeOs", "level": f"{conditions.get('difficulty_class', 'IN')} {conditions.get('difficulty_value', 15)}"},
            "judgeLineList": lines, "judgeLineGroup": ["Default"],
            "pamos": {"schema_version": "1.0.0", "chart_mode": mode, "key_count": key_count,
                      "conditions": copy.deepcopy(conditions), "duration_s": duration_s,
                      "generator": "unspecified", "client_playtest": "NOT RUN"}}


def _default_png():
    width, height = 640, 360
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            stripe = abs(y - height * 0.7) < 2 or (x % 80 < 2 and y > height * 0.7)
            rows.extend((75, 205, 196) if stripe else (12 + y // 18, 20 + x // 50, 38 + y // 14))
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + struct.pack(">I", zlib.crc32(name + data) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")


def export_package(chart, music_path, output_path, metadata, illustration_path=None):
    import yaml
    ir = chart_to_ir(chart, metadata.get("chart_mode", chart.get("pamos", {}).get("chart_mode", "regular")),
                     metadata.get("key_count", chart.get("pamos", {}).get("key_count")))
    from .audit import audit_chart
    audit = audit_chart(chart, conditions={**metadata.get("conditions", {}), "chart_mode": ir["chart_mode"], "key_count": ir["key_count"]})
    if audit["status"] == "BLOCK":
        raise ValueError("导出前发现确定性错误: " + "; ".join(i["code"] for i in audit["issues"] if i["severity"] == "BLOCK"))
    if ir["chart_mode"] == "pure_keys" and any(i["code"] == "PURE_KEYS_STATIC_UNVERIFIED" for i in audit["issues"]):
        raise ValueError("无法确认扩展字段是否破坏固定线，尚不能导出认证的纯配置包；原始 JSON 保留")
    payload = copy.deepcopy({k: v for k, v in chart.items() if k != "_pamos_import"})
    if metadata.get("chart_sha256") and metadata["chart_sha256"] != chart_hash(chart):
        raise ValueError("导出请求的谱面哈希与当前内容不匹配")
    if has_noise(payload):
        raise ValueError("含噪域谱面可只读保存 JSON；当前打包器不能认证噪域素材依赖完整性，拒绝有损打包")
    if any(isinstance(layer, dict) and layer.get("skin") for layer in payload.get("noiseAreaLayers", [])):
        raise ValueError("噪域层包含皮肤引用，当前打包器不能认证素材依赖完整性")
    for line in payload["judgeLineList"]:
        if line.get("Texture", "line.png") != "line.png":
            raise ValueError("当前打包器没有导入自定义判定线素材；拒绝产生缺失依赖的包")
        for note in line.get("notes") or []:
            if note.get("hitsound"):
                raise ValueError("当前打包器没有导入自定义音效；拒绝产生缺失依赖的包")
    if any(payload.get(key) for key in ("shaders", "effects", "extra", "assets", "shaderList")):
        raise ValueError("当前打包器不能携带扩展素材依赖，原始 JSON 保持不变")
    total_ms = ir["offset_ms"] + ir["info_offset_s"] * 1000
    if abs(total_ms - round(total_ms)) > 1e-6:
        raise ValueError("客户端 META.offset 要求整数毫秒；非整毫秒 info.offset 不能无损合并")
    payload["META"]["offset"] = int(round(total_ms))
    music_path, output_path = Path(music_path), Path(output_path)
    if music_path.suffix.lower() not in {".wav", ".ogg", ".mp3", ".flac", ".m4a"}:
        raise ValueError("不支持此音频扩展名")
    if music_path.stat().st_size > MAX_PACKAGE_BYTES:
        raise ValueError("音频超过打包限额")
    music_name = "music" + music_path.suffix.lower()
    image_name = "illustration.png"
    if illustration_path is not None:
        illustration_path = Path(illustration_path)
        if illustration_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or illustration_path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("曲绘格式或大小不支持")
        image_name = "illustration" + illustration_path.suffix.lower()
    source_info = copy.deepcopy(chart.get("_pamos_import", {}).get("info", {})) if chart.get("_pamos_import", {}).get("info_format") != "rpe_text" else {}
    if source_info.get("unlockVideo"):
        raise ValueError("当前打包器不能携带解锁视频，拒绝产生缺失资源的包")
    info = {**source_info, "name": str(metadata.get("name", source_info.get("name", payload["META"].get("name", "PAMOs candidate")))),
            "difficulty": float(metadata.get("difficulty", metadata.get("difficulty_value", metadata.get("conditions", {}).get("difficulty_value", 15)))),
            "level": str(metadata.get("level", payload["META"].get("level", "IN 15"))),
            "charter": str(metadata.get("charter", source_info.get("charter", "PhiAiMadeOs"))),
            "composer": str(metadata.get("composer", source_info.get("composer", payload["META"].get("composer", "Unknown")))),
            "illustrator": str(metadata.get("illustrator", "PAMOs procedural" if illustration_path is None else "Unknown")),
            "chart": "chart.json", "format": "rpe", "music": music_name, "illustration": image_name,
            "previewStart": float(metadata.get("previewStart", source_info.get("previewStart", 0))), "offset": 0.0,
            "aspectRatio": float(metadata.get("aspectRatio", source_info.get("aspectRatio", 16 / 9))),
            "backgroundDim": float(metadata.get("backgroundDim", source_info.get("backgroundDim", 0.6)))}
    _check_tree(info)
    chart_data = canonical_bytes(payload)
    if len(chart_data) > MAX_JSON_BYTES:
        raise ValueError("导出谱面超过 JSON 安全限额")
    image_size = illustration_path.stat().st_size if illustration_path else 128 * 1024
    if len(chart_data) + music_path.stat().st_size + image_size + 65536 > MAX_PACKAGE_BYTES:
        raise ValueError("导出包总输入体积超过256 MiB限额")
    # A new output is required: export cannot overwrite an earlier immutable artifact.
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("xb") as target:
            with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.writestr("info.yml", yaml.safe_dump(info, allow_unicode=True, sort_keys=False))
                archive.writestr("chart.json", chart_data)
                archive.write(music_path, music_name)
                if illustration_path is None:
                    archive.writestr(image_name, _default_png())
                else:
                    archive.write(illustration_path, image_name)
    except BaseException:
        # Remove only this invocation's partial artifact, never a pre-existing file.
        if 'target' in locals():
            output_path.unlink(missing_ok=True)
        raise
    limitations = list(ir["unsupported_features"])
    limitations += ["共同 RPE 结构适配；未经原 RPE/Next 双向无损认证", "复杂父子线/扩展几何需人工确认", "Phira-Pro 导入试玩 NOT RUN", "导出再导入回归 NOT RUN"]
    return {"path": str(output_path), "sha256": _file_hash(output_path), "chart_sha256": chart_hash(payload),
            "compatibility_limits": limitations, "warnings": ir["warnings"], "info": info,
            "offset_conversion": {"source_meta_ms": ir["offset_ms"], "source_info_s": ir["info_offset_s"],
                                  "export_meta_ms": payload["META"]["offset"], "export_info_s": 0},
            "default_illustration": illustration_path is None, "client_playtest": "NOT RUN"}
