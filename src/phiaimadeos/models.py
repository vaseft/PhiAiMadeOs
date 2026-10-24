"""Small learned models. Importing this module does not import PyTorch.

Call ``build_model`` only inside the exclusive training/generation worker.
The canonical event families below are a reversible, deliberately restricted
motion dictionary, not claims of support for arbitrary RPE extension events.
"""
from __future__ import annotations

import math

ARCH_VERSION = "pamos-transformer-192-v2"
FEATURE_DIM = 104
FEATURE_RATE = 25.0
MAX_AUDIO_FRAMES = 384
MAX_NOTE_SLOTS = 192
MAX_MOTION_EVENTS = 320
MAX_LINES = 64
LINE_CAPACITIES = (64, 128, 512)
TIME_CELLS = 32
VOICES = 6
CONDITION_DIM = 41
POSITION_X_SCALE = 1350.0
KINDS = ("TAP", "HOLD", "DRAG", "FLICK")
MOTION_PROPERTIES = ("moveXEvents", "moveYEvents", "rotateEvents", "alphaEvents", "speedEvents")
MOTION_SCALES = (675.0, 450.0, 180.0, 255.0, 1.0)
MOTION_DICTIONARY_VERSION = "train-fitted-endpoints64-easing29-v1"
_CLASSES = None


class ModelError(ValueError):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.details}


def motion_capacity(max_lines: int = MAX_LINES) -> int:
    if isinstance(max_lines, bool) or not isinstance(max_lines, int) or max_lines not in LINE_CAPACITIES:
        raise ModelError("INVALID_LINE_CAPACITY", "判定线容量必须为 64、128 或 512。")
    return max(64, max_lines * len(MOTION_PROPERTIES))


def encode_conditions(conditions: dict, *, training=False) -> list[float]:
    """Encode observed labels, including masks for unobserved continuous labels."""
    mode = conditions.get("chart_mode")
    if mode not in ("regular", "pure_keys"):
        raise ModelError("UNSUPPORTED_MODE", "学习模型当前仅支持常规与纯配置；异像机制尚未验收。")
    key = conditions.get("key_count")
    if mode == "pure_keys" and key not in (4, 5, 6):
        raise ModelError("INVALID_KEY_COUNT", "纯配置必须明确标注 4K、5K 或 6K。")
    if mode != "pure_keys" and key is not None:
        raise ModelError("INVALID_KEY_COUNT", "常规模式不能携带固定 K 标签。")
    if conditions.get("special_features"):
        raise ModelError("UNSUPPORTED_TARGET", "当前学习目标不包含特殊机制或噪域。")
    difficulty = conditions.get("difficulty_class")
    value = conditions.get("difficulty_value")
    ranges = {"EZ": (0, 10), "HD": (11, 14), "IN": (14, 17), "AT": (15, 18)}
    observed = difficulty is not None or value is not None
    if observed:
        if (difficulty not in ranges or isinstance(value, bool) or not isinstance(value, int)
                or not ranges[difficulty][0] <= value <= ranges[difficulty][1]):
            raise ModelError("INVALID_DIFFICULTY", "生成难度必须为已声明类别范围内的整数；源小数难度不可舍入替代。")
    elif not training:
        raise ModelError("CONDITION_LABEL_MISSING", "生成需明确难度类别及整数难度数值。")
    result = [float(mode == x) for x in ("regular", "pure_keys", "anomaly")]
    result += [float((key or 0) == x) for x in (0, 4, 5, 6)]
    result += [float(difficulty == x) for x in ("EZ", "HD", "IN", "AT")]
    result += [float(value) / 18.0 if observed else 0.0]
    for field in ("performance_intensity", "wildness"):
        v = conditions.get(field)
        if v is not None and (not math.isfinite(float(v)) or not 0 <= float(v) <= 100):
            raise ModelError("INVALID_CONDITION", f"{field} 必须在 0..100。")
        result += [0.0 if v is None else float(v) / 100.0, float(v is not None)]
    style = conditions.get("performance_style")
    result += [float(style == x) for x in ("none", "calm", "standard", "rhythm_linked", "ornate", "experimental")]
    result += [float(style is not None)]
    priority = conditions.get("generation_priority")
    result += [float(priority == x) for x in ("playability", "balanced", "performance")]
    result += [float(priority is not None), float(mode == "pure_keys"), 1.0]
    # Source ratings are separate observations, never canonical generation labels.
    result += [float(observed), float(observed)]
    source = conditions.get("source_level") or {}
    if not isinstance(source, dict):
        raise ModelError("INVALID_CONDITION", "source_level 训练标签必须是对象。")
    source_class = source.get("source_difficulty_class")
    source_value = source.get("source_difficulty_value")
    source_classes = ("EZ", "HD", "IN", "AT", "SP", "LEGACY", "BND")
    source_class = str(source_class).upper() if source_class is not None else None
    source_observed = source_value is not None
    if source_observed and (isinstance(source_value, bool) or not isinstance(source_value, (int, float))
                            or not math.isfinite(source_value) or not 0 <= source_value <= 100):
        raise ModelError("INVALID_CONDITION", "源难度数值必须为 0..100 内的有限数字或缺失。")
    result += [float(source_class == x) for x in source_classes]
    result += [float(source_value) / 20.0 if source_observed else 0.0,
               float(source_class in source_classes), float(source_observed)]
    if mode == "pure_keys" and (conditions.get("performance_intensity", 0) not in (None, 0)
                                or style not in (None, "none")):
        raise ModelError("PURE_KEYS_NOT_NORMALIZED", "纯配置条件需先规范化：演出强度为 0、风格为 none。")
    assert len(result) == CONDITION_DIM
    return result


def model_config(stage: str, max_lines: int = MAX_LINES) -> dict:
    if stage not in ("note_rhythm", "line_motion", "placement"):
        raise ModelError("INVALID_STAGE", "未知模型阶段。", stage=stage)
    if isinstance(max_lines, bool) or not isinstance(max_lines, int) or max_lines not in LINE_CAPACITIES:
        raise ModelError("INVALID_LINE_CAPACITY", "判定线容量必须为 64、128 或 512。")
    return {"stage": stage, "arch_version": ARCH_VERSION, "d_model": 192,
            "heads": 4, "audio_layers": 2, "decoder_layers": 4 if stage == "note_rhythm" else 3,
            "feature_dim": FEATURE_DIM, "condition_dim": CONDITION_DIM,
            "max_audio_frames": MAX_AUDIO_FRAMES, "max_note_slots": MAX_NOTE_SLOTS,
            "max_motion_events": motion_capacity(max_lines), "max_lines": max_lines,
            "parent_head": "factorized-rank32-dag", "line_context_dim": 14,
            "condition_version": "canonical-masked-source-continuous-v2",
            "position_x_scale": POSITION_X_SCALE,
            "motion_dictionary_version": MOTION_DICTIONARY_VERSION}


def _load_classes():
    global _CLASSES
    if _CLASSES is not None:
        return _CLASSES
    import torch
    from torch import nn

    class AudioConditionEncoder(nn.Module):
        def __init__(self):
            super().__init__()
            self.input = nn.Sequential(nn.LayerNorm(FEATURE_DIM), nn.Linear(FEATURE_DIM, 192), nn.GELU())
            self.condition = nn.Sequential(nn.Linear(CONDITION_DIM, 192), nn.GELU(), nn.Linear(192, 192))
            layer = nn.TransformerEncoderLayer(192, 4, 768, 0.1, batch_first=True, norm_first=True)
            self.encoder = nn.TransformerEncoder(layer, 2, enable_nested_tensor=False)
            self.norm = nn.LayerNorm(192)

        def forward(self, audio, conditions, audio_mask=None):
            if audio.shape[1] > MAX_AUDIO_FRAMES or audio.shape[-1] != FEATURE_DIM:
                raise ModelError("INVALID_FEATURE_SHAPE", "音频窗口超过 384 帧或特征维度不是 104。")
            t = audio.shape[1]
            position = torch.arange(t, device=audio.device, dtype=torch.float32)[:, None]
            freq = torch.exp(torch.arange(0, 192, 2, device=audio.device, dtype=torch.float32) * (-math.log(10000.0) / 192))
            pe = torch.zeros(t, 192, device=audio.device, dtype=torch.float32)
            pe[:, 0::2], pe[:, 1::2] = torch.sin(position * freq), torch.cos(position * freq)
            encoded = self.input(audio) + pe.to(audio.dtype)[None]
            encoded = torch.cat((self.condition(conditions)[:, None], encoded), dim=1)
            mask = None
            if audio_mask is not None:
                mask = torch.cat((torch.zeros(audio.shape[0], 1, device=audio.device, dtype=torch.bool), audio_mask), dim=1)
            return self.norm(self.encoder(encoded, src_key_padding_mask=mask)), mask

    class EventDecoder(nn.Module):
        def __init__(self, query_dim, layers):
            super().__init__()
            self.query = nn.Sequential(nn.Linear(query_dim, 192), nn.GELU(), nn.Linear(192, 192))
            self.decoder = nn.TransformerDecoder(nn.TransformerDecoderLayer(
                192, 4, 768, 0.1, batch_first=True, norm_first=True), layers, norm=nn.LayerNorm(192))

        def forward(self, query, memory, memory_mask=None, query_mask=None):
            return self.decoder(self.query(query), memory, tgt_key_padding_mask=query_mask,
                                memory_key_padding_mask=memory_mask)

    class KLanePlacementHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.projection = nn.Linear(192, 6)

        def forward(self, hidden, key_count):
            logits = self.projection(hidden)
            k = torch.as_tensor(key_count, device=hidden.device).reshape(-1, 1, 1)
            invalid = torch.arange(6, device=hidden.device).reshape(1, 1, 6) >= k
            return logits.masked_fill(invalid, -1e4)

    class NoteRhythmNet(nn.Module):
        def __init__(self, max_lines=MAX_LINES):
            super().__init__()
            self.max_lines = max_lines
            self.audio = AudioConditionEncoder()
            self.events = EventDecoder(8, 4)
            self.presence = nn.Linear(192, 1)
            self.kind = nn.Linear(192, 4)
            self.residual = nn.Linear(192, 1)
            self.hold = nn.Linear(192, 1)
            self.lanes = KLanePlacementHead()

        def forward(self, features, conditions, queries, key_count=6, audio_mask=None):
            memory, mask = self.audio(features, conditions, audio_mask)
            hidden = self.events(queries, memory, mask)
            return {"presence": self.presence(hidden).squeeze(-1), "kind": self.kind(hidden),
                    "residual": torch.tanh(self.residual(hidden).squeeze(-1)) * 0.5,
                    "hold": torch.nn.functional.softplus(self.hold(hidden).squeeze(-1)),
                    "lane": self.lanes(hidden, key_count)}

    class LineMotionNet(nn.Module):
        def __init__(self, max_lines=MAX_LINES):
            super().__init__()
            self.max_lines = max_lines
            self.audio = AudioConditionEncoder()
            self.notes = nn.Linear(16, 192)
            self.events = EventDecoder(8, 3)
            self.presence = nn.Linear(192, 1)
            self.line = nn.Linear(192, max_lines)
            self.property = nn.Linear(192, 5)
            self.easing = nn.Linear(192, 29)
            self.prototype = nn.Linear(192, 64)
            self.params = nn.Linear(192, 6)
            self.line_count = nn.Linear(192, max_lines)
            self.parent_query = nn.Embedding(max_lines, 32)
            self.parent_key = nn.Embedding(max_lines + 1, 32)
            self.parent_condition = nn.Linear(192, 64)
            self.register_buffer("prototype_centers", torch.zeros(64, 2))
            self.register_buffer("prototype_properties", torch.full((64,), -1, dtype=torch.long))

        def forward(self, features, conditions, queries, notes, audio_mask=None):
            memory, mask = self.audio(features, conditions, audio_mask)
            summary = memory[:, 0]
            parent_condition = self.parent_condition(summary)
            parent_queries = self.parent_query.weight[None] + parent_condition[:, None, :32]
            parent_keys = self.parent_key.weight[None] + parent_condition[:, None, 32:]
            parents = torch.matmul(parent_queries, parent_keys.transpose(-1, -2)) / math.sqrt(32)
            invalid = torch.arange(self.max_lines + 1, device=summary.device)[None, :] > torch.arange(self.max_lines, device=summary.device)[:, None]
            parents = parents.masked_fill(invalid[None], -1e4)
            memory = torch.cat((memory, self.notes(notes)), dim=1)
            if mask is not None:
                mask = torch.cat((mask, torch.zeros(notes.shape[:2], dtype=torch.bool, device=notes.device)), dim=1)
            h = self.events(queries, memory, mask)
            p = self.params(h)
            if not bool((self.prototype_properties >= 0).any()):
                raise ModelError("MOTION_DICTIONARY_UNAVAILABLE", "LineMotionNet缺少训练集拟合的运动原型。")
            prototypes = self.prototype(h).masked_fill(self.prototype_properties[None, None] < 0, -1e4)
            # Differentiable prototype mixture plus continuous endpoint residuals.
            endpoint_base = prototypes.float().softmax(-1) @ self.prototype_centers.float()
            return {"presence": self.presence(h).squeeze(-1), "line": self.line(h),
                    "property": self.property(h), "easing": self.easing(h), "prototype": prototypes,
                    "start": torch.sigmoid(p[..., 0]), "duration": torch.nn.functional.softplus(p[..., 1]),
                    "values": p[..., 2:4] + endpoint_base, "line_count": self.line_count(summary),
                    "easing_bounds": torch.stack((torch.sigmoid(p[..., 4]),
                        torch.sigmoid(p[..., 4]) + (1 - torch.sigmoid(p[..., 4])) * torch.sigmoid(p[..., 5])), dim=-1),
                    "parents": parents}

    class PlacementNet(nn.Module):
        def __init__(self, max_lines=MAX_LINES):
            super().__init__()
            self.max_lines = max_lines
            self.audio = AudioConditionEncoder()
            self.line_context = nn.Linear(14, 192)
            self.events = EventDecoder(16, 3)
            self.line = nn.Linear(192, max_lines)
            self.x = nn.Linear(192, 1)
            self.above = nn.Linear(192, 2)
            self.extra = nn.Linear(192, 2)
            self.lanes = KLanePlacementHead()

        def forward(self, features, conditions, queries, lines, key_count=6, audio_mask=None):
            memory, mask = self.audio(features, conditions, audio_mask)
            memory = torch.cat((memory, self.line_context(lines)), dim=1)
            if mask is not None:
                mask = torch.cat((mask, torch.zeros(lines.shape[:2], device=lines.device, dtype=torch.bool)), dim=1)
            h = self.events(queries, memory, mask)
            extra = self.extra(h)
            return {"line": self.line(h), "x": torch.tanh(self.x(h).squeeze(-1)),
                    "above": self.above(h), "y_offset": torch.tanh(extra[..., 0]),
                    "speed": torch.nn.functional.softplus(extra[..., 1]),
                    "lane": self.lanes(h, key_count)}

    _CLASSES = {c.__name__: c for c in (NoteRhythmNet, LineMotionNet, PlacementNet, KLanePlacementHead)}
    return _CLASSES


def build_model(stage: str, config: dict | None = None):
    expected = model_config(stage, MAX_LINES if config is None else config.get("max_lines"))
    if config is not None and config != expected:
        raise ModelError("ARCHITECTURE_MISMATCH", "checkpoint 架构与当前实现不一致。")
    names = {"note_rhythm": "NoteRhythmNet", "line_motion": "LineMotionNet", "placement": "PlacementNet"}
    return _load_classes()[names[stage]](max_lines=expected["max_lines"])


def set_motion_dictionary(model, dictionary: dict):
    import torch
    if dictionary.get("version") != MOTION_DICTIONARY_VERSION:
        raise ModelError("MOTION_DICTIONARY_MISMATCH", "运动原型字典版本不匹配。")
    centers, properties = dictionary.get("centers", []), dictionary.get("properties", [])
    if not 1 <= len(centers) <= 64 or len(properties) != len(centers):
        raise ModelError("MOTION_DICTIONARY_MISMATCH", "运动原型字典为空或超限。")
    with torch.no_grad():
        model.prototype_centers.zero_()
        model.prototype_properties.fill_(-1)
        model.prototype_centers[:len(centers)].copy_(torch.tensor(centers, dtype=torch.float32, device=model.prototype_centers.device))
        model.prototype_properties[:len(properties)].copy_(torch.tensor(properties, dtype=torch.long, device=model.prototype_properties.device))


def __getattr__(name):
    if name in ("NoteRhythmNet", "LineMotionNet", "PlacementNet", "KLanePlacementHead"):
        return _load_classes()[name]
    raise AttributeError(name)
