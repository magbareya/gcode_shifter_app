"""G-code helpers for shifting a toolpath and measuring its extents.

Written for GRBL 1.1 (e.g. TwoTrees TTC450 Pro). The parser only rewrites the
numeric value of X/Y/Z words in place; everything else (comments, spacing,
`%` lines, `$` commands, word order, number formatting of untouched words)
is preserved byte-for-byte.

GRBL semantics that matter here:
  * G90 / G91       absolute vs incremental distance mode (modal). Only
                    absolute X/Y/Z targets may be shifted.
  * G2/G3 I J K     arc centre offsets are ALWAYS incremental in GRBL
                    (G91.1), so they must not be shifted. R is a radius.
  * G53             move in machine coordinates (non-modal) - never shift.
  * G28 / G30       axis words are an intermediate point for a safety move.
  * G10 / G92       define coordinate systems - shifting their values would
                    cancel (or double) the intended shift.
  * G43.1 Z         dynamic tool length offset, not a position.
"""

import hashlib
import math
import re

AXES = ("X", "Y", "Z")

# TwoTrees TTC450 / TTC450 Pro nominal working area in mm. Used only for a
# soft "job is larger than the machine" warning - verify against your unit.
MACHINE_TRAVEL_MM = {"X": 460.0, "Y": 460.0, "Z": 80.0}

_NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)"
_WORD_RE = re.compile(r"([A-Za-z])\s*(" + _NUM + r")")
_AXIS_RE = re.compile(r"([XYZxyz])(\s*)(" + _NUM + r")")
_COMMENT_RE = re.compile(r"\([^)]*\)?|;.*")

# G-codes whose X/Y/Z words are NOT work-coordinate targets.
NO_SHIFT_GCODES = {"10", "28", "28.1", "30", "30.1", "43.1", "53", "92", "92.1"}
MOTION_GCODES = {"0", "1", "2", "3", "38.2", "38.3", "38.4", "38.5", "80"}
CUT_MOTIONS = {"1", "2", "3"}

# Arc plane -> (axis_0, axis_1, linear_axis, offset letter for axis_0, axis_1)
_PLANES = {
    "17": ("X", "Y", "Z", "I", "J"),
    "18": ("Z", "X", "Y", "K", "I"),
    "19": ("Y", "Z", "X", "J", "K"),
}


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def _split_line_ending(raw):
    body = raw.rstrip("\r\n")
    return body, raw[len(body):]


def _code_segments(body):
    """Split a line into [(is_code, text), ...] keeping comments untouched."""
    stripped = body.strip()
    # Program delimiters and GRBL system commands ($H, $X, $$, $J=...) pass through.
    if not stripped or stripped.startswith("%") or stripped.startswith("$"):
        return [(False, body)]
    segments, pos = [], 0
    for m in _COMMENT_RE.finditer(body):
        if m.start() > pos:
            segments.append((True, body[pos:m.start()]))
        segments.append((False, m.group(0)))
        pos = m.end()
    if pos < len(body):
        segments.append((True, body[pos:]))
    return segments


def _norm_code(value):
    """'00' -> '0', '1.' -> '1', '91.1' -> '91.1'."""
    return f"{float(value):g}"


def _parse_words(segments):
    """Return (gcodes:set[str], words:dict[letter->float]) for a block.

    M-codes are returned in `words` under the key "M*" as a set.
    """
    gcodes, words, mcodes = set(), {}, set()
    for is_code, text in segments:
        if not is_code:
            continue
        for letter, value in _WORD_RE.findall(text):
            letter = letter.upper()
            if letter == "G":
                gcodes.add(_norm_code(value))
            elif letter == "M":
                mcodes.add(_norm_code(value))
            else:
                words[letter] = float(value)
    words["M*"] = mcodes
    return gcodes, words


class _State:
    def __init__(self):
        self.absolute = True
        self.plane = "17"
        self.motion = None
        self.units = "mm"
        self.pos = {a: None for a in AXES}
        self.spindle_on = None  # None = never set in the file
        self.s = None

    def apply_modal(self, gcodes, words):
        mcodes = words.get("M*", set())
        if mcodes & {"3", "4"}:
            self.spindle_on = True
        if mcodes & {"5", "2", "30"}:
            self.spindle_on = False
        if "S" in words:
            self.s = words["S"]
        for g in gcodes:
            if g == "90":
                self.absolute = True
            elif g == "91":
                self.absolute = False
            elif g in _PLANES:
                self.plane = g
            elif g == "20":
                self.units = "inch"
            elif g == "21":
                self.units = "mm"
            elif g in MOTION_GCODES:
                self.motion = g


def _walk(gcode):
    """Yield (body, ending, segments, gcodes, words, state) for every line.

    `state` has already had this block's modal codes applied (GRBL applies
    G90/G91 etc. before executing the motion in the same block) but the
    position has not yet been advanced.
    """
    state = _State()
    for raw in gcode.splitlines(keepends=True):
        body, ending = _split_line_ending(raw)
        segments = _code_segments(body)
        gcodes, words = _parse_words(segments)
        state.apply_modal(gcodes, words)
        yield body, ending, segments, gcodes, words, state


# --------------------------------------------------------------------------- #
# Shifting
# --------------------------------------------------------------------------- #
def _fmt(value, decimals=4):
    s = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def shift_gcode(gcode, x_shift=0.0, y_shift=0.0, z_shift=0.0):
    """Translate all absolute work-coordinate X/Y/Z targets by the given offsets."""
    shifts = {"X": x_shift, "Y": y_shift, "Z": z_shift}
    out = []

    for body, ending, segments, gcodes, words, state in _walk(gcode):
        has_axis = any(a in words for a in AXES)
        if not has_axis or not state.absolute or gcodes & NO_SHIFT_GCODES:
            out.append(body + ending)
            continue

        def repl(m):
            delta = shifts[m.group(1).upper()]
            if delta == 0:
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}{_fmt(float(m.group(3)) + delta)}"

        new_body = "".join(
            _AXIS_RE.sub(repl, text) if is_code else text for is_code, text in segments
        )
        out.append(new_body + ending)

    return "".join(out)


_SCALE_RE = re.compile(r"([XYIJRxyijr])(\s*)(" + _NUM + r")")


def scale_gcode(gcode, factor, ref_x=0.0, ref_y=0.0):
    """Uniformly scale the toolpath in XY by `factor` around (ref_x, ref_y).

    * Absolute X/Y:          (v - ref) * factor + ref
    * Incremental X/Y (G91): v * factor
    * Arc I/J/R:             v * factor (always incremental/radius in GRBL)
    * Z, feed (F), power/speed (S) are NOT changed.
    * G53/G28/G30/G92/G10/G43.1 lines are left untouched.

    Raises ValueError for factor <= 0 or for arcs in the G18/G19 planes (those
    mix Z into the arc, which can't be scaled while keeping Z unchanged).
    """
    if factor <= 0:
        raise ValueError("Scale factor must be greater than 0.")
    refs = {"X": ref_x, "Y": ref_y}
    out = []

    for body, ending, segments, gcodes, words, state in _walk(gcode):
        if gcodes & NO_SHIFT_GCODES or not any(k in words for k in "XYIJR"):
            out.append(body + ending)
            continue
        is_arc = state.motion in ("2", "3")
        if is_arc and state.plane != "17":
            raise ValueError("Scaling is not supported for arcs in the G18/G19 planes.")

        def repl(m):
            letter = m.group(1).upper()
            value = float(m.group(3))
            if letter in "XY":
                new = (value - refs[letter]) * factor + refs[letter] if state.absolute else value * factor
            elif is_arc:  # I, J, R only mean something on arc moves
                new = value * factor
            else:
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}{_fmt(new)}"

        new_body = "".join(
            _SCALE_RE.sub(repl, text) if is_code else text for is_code, text in segments
        )
        out.append(new_body + ending)

    return "".join(out)


# --------------------------------------------------------------------------- #
# Extents
# --------------------------------------------------------------------------- #
class _Box:
    def __init__(self):
        self.min = {a: None for a in AXES}
        self.max = {a: None for a in AXES}

    def add(self, axis, value):
        if value is None:
            return
        if self.min[axis] is None or value < self.min[axis]:
            self.min[axis] = value
        if self.max[axis] is None or value > self.max[axis]:
            self.max[axis] = value

    def add_point(self, pos):
        for a in AXES:
            self.add(a, pos.get(a))

    def to_dict(self):
        mid, size = {}, {}
        for a in AXES:
            lo, hi = self.min[a], self.max[a]
            mid[a] = None if lo is None else (lo + hi) / 2
            size[a] = None if lo is None else hi - lo
        return {"min": dict(self.min), "max": dict(self.max), "mid": mid, "size": size}


def _arc_points(start, end, words, plane, clockwise):
    """Return extra points (axis extremes) that an arc passes through."""
    a0, a1, _, off0, off1 = _PLANES[plane]
    if start[a0] is None or start[a1] is None:
        return []
    su, sv = start[a0], start[a1]
    eu, ev = end[a0], end[a1]

    if "R" in words:
        r = words["R"]
        x, y = eu - su, ev - sv
        d = math.hypot(x, y)
        if d == 0:
            return []
        h = 4 * r * r - x * x - y * y
        h = -math.sqrt(max(h, 0.0)) / d
        if not clockwise:
            h = -h
        if r < 0:
            h = -h
        cu, cv = su + 0.5 * (x - y * h), sv + 0.5 * (y + x * h)
    else:
        cu, cv = su + words.get(off0, 0.0), sv + words.get(off1, 0.0)

    radius = math.hypot(su - cu, sv - cv)
    ang_s = math.atan2(sv - cv, su - cu)
    ang_e = math.atan2(ev - cv, eu - cu)
    two_pi = 2 * math.pi
    sweep = ((ang_s - ang_e) if clockwise else (ang_e - ang_s)) % two_pi
    if sweep < 1e-9 and "R" not in words:
        sweep = two_pi  # full circle

    points = []
    for k in range(4):
        theta = k * math.pi / 2
        delta = ((ang_s - theta) if clockwise else (theta - ang_s)) % two_pi
        if delta <= sweep:
            points.append({a0: cu + radius * math.cos(theta), a1: cv + radius * math.sin(theta)})
    return points


def get_gcode_info(gcode):
    """Simulate the program and return extents, units and warnings.

    Returns {"units", "cut": box, "all": box, "warnings": [...]}, where `cut`
    covers feed moves (G1/G2/G3) with the spindle/laser on and S != 0 - i.e.
    the actual cut/engraved "image" - and `all` includes every move (rapids,
    laser-off travel, overscan). Each box
    is {"min","max","mid","size"} with X/Y/Z keys (None if never used).
    """
    cut, every = _Box(), _Box()
    warnings = set()
    units_seen = set()
    state = None

    for _, _, _, gcodes, words, state in _walk(gcode):
        units_seen.add(state.units)
        if "91" in gcodes:
            warnings.add("Program uses G91 (incremental) moves - those are not shifted, which is correct.")
        if "92" in gcodes:
            warnings.add("Program uses G92 (coordinate offset) - its values are left untouched.")
        if gcodes & {"53", "28", "30"}:
            warnings.add("Program contains G53/G28/G30 moves - they are machine/safety moves and are not shifted or measured.")

        if not any(a in words for a in AXES) or gcodes & NO_SHIFT_GCODES:
            continue
        if state.motion in (None, "80"):
            continue

        start = dict(state.pos)
        end = dict(start)
        for a in AXES:
            if a in words:
                if state.absolute:
                    end[a] = words[a]
                elif start[a] is not None:
                    end[a] = start[a] + words[a]
                else:
                    end[a] = None  # incremental from unknown position

        # A feed move only "cuts/burns" if the spindle/laser is not explicitly
        # off and S is not 0 (laser files use G1 ... S0 for travel/overscan).
        cutting = (
            state.motion in CUT_MOTIONS
            and state.spindle_on is not False
            and state.s != 0
        )
        boxes = [every] + ([cut] if cutting else [])
        for box in boxes:
            if cutting:
                box.add_point(start)
            box.add_point(end)
            if state.motion in ("2", "3"):
                for p in _arc_points(start, end, words, state.plane, state.motion == "2"):
                    box.add_point(p)

        state.pos = end

    units = "inch" if "inch" in units_seen and len(units_seen) == 1 else "mm"
    if len(units_seen) > 1:
        warnings.add("Program switches between G20 (inch) and G21 (mm) - extents may be wrong.")
    elif units == "inch":
        warnings.add("Program is in inches (G20) - all values and shifts are in inches.")

    info = {"units": units, "cut": cut.to_dict(), "all": every.to_dict()}

    scale = 25.4 if units == "inch" else 1.0
    for a in AXES:
        size = info["all"]["size"][a]
        if size is not None and size * scale > MACHINE_TRAVEL_MM[a]:
            warnings.add(
                f"{a} extent {size * scale:.1f} mm is larger than the TTC450 travel "
                f"({MACHINE_TRAVEL_MM[a]:.0f} mm)."
            )

    info["warnings"] = sorted(warnings)
    return info


def alignment_box(info):
    """Box used for Move/Set operations: feed moves if any, else all moves."""
    if info["cut"]["min"]["X"] is not None or info["cut"]["min"]["Y"] is not None:
        return info["cut"]
    return info["all"]


def get_hash(content):
    return hashlib.md5(content.encode("utf-8")).hexdigest()
