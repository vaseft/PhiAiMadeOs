"""Independent mathematical evaluation of the public RPE scalar event contract.

No editor source is copied. Extended trajectories and control curves are reported
by the auditor instead of being treated as verified geometry.
"""
from bisect import bisect_right
import math


def _bounce_out(x):
    if x < 1 / 2.75:
        return 7.5625 * x * x
    if x < 2 / 2.75:
        x -= 1.5 / 2.75
        return 7.5625 * x * x + 0.75
    if x < 2.5 / 2.75:
        x -= 2.25 / 2.75
        return 7.5625 * x * x + 0.9375
    x -= 2.625 / 2.75
    return 7.5625 * x * x + 0.984375


def _ease_in(family, x):
    if family == "sine":
        return 1 - math.cos(x * math.pi / 2)
    if family in {"quad", "cubic", "quart", "quint"}:
        return x ** {"quad": 2, "cubic": 3, "quart": 4, "quint": 5}[family]
    if family == "expo":
        return 0 if x == 0 else 2 ** (10 * x - 10)
    if family == "circ":
        return 1 - math.sqrt(max(0, 1 - x * x))
    if family == "back":
        return 2.70158 * x ** 3 - 1.70158 * x * x
    if family == "elastic":
        return x if x in (0, 1) else -(2 ** (10 * x - 10)) * math.sin((10 * x - 10.75) * 2 * math.pi / 3)
    if family == "bounce":
        return 1 - _bounce_out(1 - x)
    return x


EASES = {2: ("sine", "out"), 3: ("sine", "in"), 4: ("quad", "out"), 5: ("quad", "in"),
         6: ("sine", "inout"), 7: ("quad", "inout"), 8: ("cubic", "out"), 9: ("cubic", "in"),
         10: ("quart", "out"), 11: ("quart", "in"), 12: ("cubic", "inout"), 13: ("quart", "inout"),
         14: ("quint", "out"), 15: ("quint", "in"), 16: ("expo", "out"), 17: ("expo", "in"),
         18: ("circ", "out"), 19: ("circ", "in"), 20: ("back", "out"), 21: ("back", "in"),
         22: ("circ", "inout"), 23: ("back", "inout"), 24: ("elastic", "out"), 25: ("elastic", "in"),
         26: ("bounce", "out"), 27: ("bounce", "in"), 28: ("bounce", "inout"), 29: ("elastic", "inout")}


def ease(kind, x):
    x = max(0.0, min(1.0, x))
    family, direction = EASES.get(kind, ("linear", "in"))
    if direction == "in":
        return _ease_in(family, x)
    if direction == "out":
        return 1 - _ease_in(family, 1 - x)
    return _ease_in(family, 2 * x) / 2 if x < 0.5 else 1 - _ease_in(family, 2 - 2 * x) / 2


def event_fraction(event, x):
    if event.get("bezier", 0):
        x1, y1, x2, y2 = event["bezierPoints"]
        def cubic(t, a, b):
            return 3 * (1 - t) ** 2 * t * a + 3 * (1 - t) * t * t * b + t ** 3
        left, right = 0.0, 1.0
        for _ in range(35):
            middle = (left + right) / 2
            if cubic(middle, x1, x2) < x:
                left = middle
            else:
                right = middle
        return cubic((left + right) / 2, y1, y2)
    kind = event.get("easingType", 1)
    left, right = event.get("easingLeft", 0), event.get("easingRight", 1)
    if kind <= 1 or left >= right or (left == 0 and right == 1):
        return ease(kind, x)
    start, end = ease(kind, left), ease(kind, right)
    if abs(end - start) < 1e-12:
        return x
    return (ease(kind, left + (right - left) * x) - start) / (end - start)


def compile_track(events):
    events = sorted(events, key=lambda item: item[0])
    return ([event[0] for event in events], events)


def track_value(track, time_s, default=0):
    starts, events = track
    if not events:
        return default
    index = max(0, bisect_right(starts, time_s) - 1)
    start_s, end_s, event = events[index]
    if time_s < start_s:
        return event["start"]
    if time_s >= end_s or end_s <= start_s:
        return event["end"]
    factor = event_fraction(event, (time_s - start_s) / (end_s - start_s))
    return event["start"] + (event["end"] - event["start"]) * factor


def scalar_value(tracks, name, time_s, default=0):
    layers = tracks.get(name, [])
    return sum(track_value(track, time_s, 0) for track in layers) if layers else default


def line_transform(index, time_s, lines, compiled, memo=None):
    memo = {} if memo is None else memo
    if index in memo:
        return memo[index]
    line, tracks = lines[index], compiled[index]
    x = scalar_value(tracks, "moveXEvents", time_s) / 675
    y = scalar_value(tracks, "moveYEvents", time_s) / 450
    angle = -scalar_value(tracks, "rotateEvents", time_s)
    parent = line.get("father", -1)
    if parent is not None and parent >= 0:
        px, py, parent_angle = line_transform(parent, time_s, lines, compiled, memo)
        radians = math.radians(parent_angle)
        x, y = px + x * math.cos(radians) - y * math.sin(radians), py + x * math.sin(radians) + y * math.cos(radians)
        if line.get("rotateWithFather", True):
            angle += parent_angle
    memo[index] = (x, y, angle)
    return memo[index]


def note_position(note, transform):
    x, y, angle = transform
    radians = math.radians(angle)
    local_x = note["x"] / 675
    # yOffset/control curves have additional client semantics: the auditor warns.
    return x + local_x * math.cos(radians), y + local_x * math.sin(radians)
