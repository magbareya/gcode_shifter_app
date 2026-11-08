"""G-code helpers: shift, scale, measure and preview a toolpath.

Written for GRBL 1.1 (e.g. TwoTrees TTC450 Pro, router or laser module). The
editor only rewrites the numeric value of the words it changes; everything
else (comments, spacing, `%` lines, `$` commands, word order, formatting of
untouched numbers) is preserved byte-for-byte.

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
  * M3/M4/M5, S     spindle / laser on-off and speed / power. A feed move
                    with S0 (laser overscan / travel) is not a "cut".
  * F               feed rate, modal. G0 ignores it (always max rate $110/$111).
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
_SCALE_RE = re.compile(r"([XYIJRxyijr])(\s*)(" + _NUM + r")")
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
    """Return (gcodes, mcodes, words) for a block; words maps letter -> float."""
    gcodes, mcodes, words = set(), set(), {}
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
    return gcodes, mcodes, words


class _State:
    def __init__(self):
        self.absolute = True
        self.plane = "17"
        self.motion = None
        self.units = "mm"
        self.pos = {a: None for a in AXES}
        self.spindle_on = None  # None = never set in the file
        self.s = None
        self.f = None
        self.inverse_time = False  # G93
        self.used_m4 = False

    def apply_modal(self, gcodes, mcodes, words):
        if mcodes & {"3", "4"}:
            self.spindle_on = True
        if "4" in mcodes:
            self.used_m4 = True
        if "F" in words:
            self.f = words["F"]
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
            elif g == "93":
                self.inverse_time = True
            elif g == "94":
                self.inverse_time = False
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
        gcodes, mcodes, words = _parse_words(segments)
        state.apply_modal(gcodes, mcodes, words)
        yield body, ending, segments, gcodes, words, state


def _fmt(value, decimals=4):
    s = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _rewrite(segments, pattern, repl):
    return "".join(pattern.sub(repl, text) if is_code else text for is_code, text in segments)


# --------------------------------------------------------------------------- #
# Transformations
# --------------------------------------------------------------------------- #
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

        out.append(_rewrite(segments, _AXIS_RE, repl) + ending)

    return "".join(out)


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
    if not math.isfinite(factor) or factor <= 0:
        raise ValueError("Scale factor must be greater than 0.")
    refs = {"X": ref_x, "Y": ref_y}
    out = []

    for body, ending, segments, gcodes, words, state in _walk(gcode):
        if gcodes & NO_SHIFT_GCODES:
            out.append(body + ending)
            continue
        if not any(k in words for k in "XYZIJKR"):
            out.append(body + ending)
            continue
        is_arc = state.motion in ("2", "3")
        if is_arc and state.plane != "17":
            raise ValueError("Scaling is not supported for arcs in the G18/G19 planes.")

        def repl(m):
            letter = m.group(1).upper()
            value = float(m.group(3))
            if letter in "XY":
                if state.absolute:
                    new = (value - refs[letter]) * factor + refs[letter]
                else:
                    new = value * factor
            elif is_arc:  # I, J, R only mean something on arc moves
                new = value * factor
            else:
                return m.group(0)
            if new == value:
                return m.group(0)
            return f"{m.group(1)}{m.group(2)}{_fmt(new)}"

        out.append(_rewrite(segments, _SCALE_RE, repl) + ending)

    return "".join(out)


# --------------------------------------------------------------------------- #
# Simulation (extents + preview)
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


def _arc_geometry(start, end, words, plane, clockwise):
    """Return (cu, cv, radius, start_angle, sweep, a0, a1) or None."""
    a0, a1, _, off0, off1 = _PLANES[plane]
    if None in (start[a0], start[a1], end[a0], end[a1]):
        return None
    su, sv = start[a0], start[a1]
    eu, ev = end[a0], end[a1]

    if "R" in words:  # same centre calculation GRBL uses (gcode.c)
        r = words["R"]
        x, y = eu - su, ev - sv
        d = math.hypot(x, y)
        if d == 0:
            return None
        h = -math.sqrt(max(4 * r * r - x * x - y * y, 0.0)) / d
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
    sweep = ((ang_s - ang_e) if clockwise else (ang_e - ang_s)) % (2 * math.pi)
    if sweep < 1e-9 and "R" not in words:
        sweep = 2 * math.pi  # full circle
    return cu, cv, radius, ang_s, sweep, a0, a1


def _arc_extremes(start, end, words, plane, clockwise):
    """Axis-extreme points (0/90/180/270 deg) that an arc passes through."""
    geo = _arc_geometry(start, end, words, plane, clockwise)
    if geo is None:
        return []
    cu, cv, radius, ang_s, sweep, a0, a1 = geo
    points = []
    for k in range(4):
        theta = k * math.pi / 2
        delta = ((ang_s - theta) if clockwise else (theta - ang_s)) % (2 * math.pi)
        if delta <= sweep:
            points.append({a0: cu + radius * math.cos(theta), a1: cv + radius * math.sin(theta)})
    return points


def _arc_polyline(start, end, words, plane, clockwise, step_deg=10.0):
    """XY points along an arc, excluding the start point."""
    geo = _arc_geometry(start, end, words, plane, clockwise)
    if geo is None or plane != "17":
        return [(end["X"], end["Y"])]
    cu, cv, radius, ang_s, sweep, _, _ = geo
    n = max(2, int(math.degrees(sweep) / step_deg) + 1)
    sign = -1 if clockwise else 1
    pts = [
        (cu + radius * math.cos(ang_s + sign * sweep * i / n), cv + radius * math.sin(ang_s + sign * sweep * i / n))
        for i in range(1, n)
    ]
    pts.append((end["X"], end["Y"]))
    return pts


def _is_motion_line(gcodes, words, state):
    """True if this block makes an ordinary work-coordinate move."""
    return (
        (any(a in words for a in AXES) or
         (state.motion in {"2", "3"} and any(a in words for a in "IJK")))
        and not gcodes & NO_SHIFT_GCODES
        and state.motion not in (None, "80")
    )


def _is_cutting(state):
    # A feed move only cuts/burns if the spindle/laser isn't explicitly off
    # and S isn't 0 (laser files use G1 ... S0 for travel/overscan).
    return state.motion in CUT_MOTIONS and state.spindle_on is not False and state.s != 0


def _move_kind(gcodes, words, state):
    """'rapid' (G0), 'work' (feed move, tool on), 'idle' (feed move, tool off) or None."""
    if not _is_motion_line(gcodes, words, state):
        return None
    if state.motion == "0":
        return "rapid"
    if state.motion in CUT_MOTIONS:
        return "work" if _is_cutting(state) else "idle"
    return None  # probing


def _simulate(gcode):
    """Yield (gcodes, state, move) per line; move is None for non-motion lines.

    move = {"start", "end", "words", "cutting", "arc": None | "cw" | "ccw"}
    """
    for _, _, _, gcodes, words, state in _walk(gcode):
        move = None
        # These blocks change the work-coordinate position without an ordinary
        # work move. Never connect subsequent paths to the stale position.
        if "92" in gcodes:
            for a in AXES:
                if a in words:
                    state.pos[a] = words[a]
        elif gcodes & {"10", "92.1", "43.1", "49", "54", "55", "56", "57", "58", "59"}:
            state.pos = dict.fromkeys(AXES)
        elif gcodes & {"28", "30"}:
            state.pos = dict.fromkeys(AXES)
        elif "53" in gcodes:
            for a in AXES:
                if a in words:
                    state.pos[a] = None
        if _is_motion_line(gcodes, words, state):
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
            move = {
                "start": start,
                "end": end,
                "words": words,
                "kind": _move_kind(gcodes, words, state),
                "cutting": _is_cutting(state),
                "arc": {"2": "cw", "3": "ccw"}.get(state.motion),
            }
            state.pos = end
        yield gcodes, state, move


def get_gcode_info(gcode):
    """Simulate the program and return extents, units and notices.

    Returns {"units", "cut", "all", "can_scale", "notices": [(level, text)]}.
    `cut` covers feed moves with the spindle/laser on and S != 0 - the actual
    cut/engraved "image". `all` includes every move (rapids, laser-off
    travel, overscan). Each box is {"min","max","mid","size"} with X/Y/Z keys
    (None if the axis is never used).
    """
    cut, every = _Box(), _Box()
    notices = set()
    units_seen = set()
    has_g18_19_arcs = False

    for gcodes, state, move in _simulate(gcode):
        if move is not None or gcodes & {"20", "21"}:
            units_seen.add(state.units)
        if "92" in gcodes:
            notices.add(("info", "Uses G92 coordinate offsets - those lines are kept as-is."))
        if gcodes & {"53", "28", "30"}:
            notices.add(("info", "Contains machine/safety moves (G53/G28/G30) - kept as-is and not measured."))
        if move is None:
            continue
        if move["arc"] and state.plane != "17":
            has_g18_19_arcs = True
        for box in [every] + ([cut] if move["cutting"] else []):
            if move["cutting"]:
                box.add_point(move["start"])
            box.add_point(move["end"])
            if move["arc"]:
                for p in _arc_extremes(move["start"], move["end"], move["words"], state.plane, move["arc"] == "cw"):
                    box.add_point(p)

    units = "inch" if units_seen == {"inch"} else "mm"
    if len(units_seen) > 1:
        notices.add(("warning", "Switches between inch (G20) and mm (G21) - sizes may be wrong."))
    elif units == "inch":
        notices.add(("info", "File is in inches (G20) - all values you enter are in inches."))
    if has_g18_19_arcs:
        notices.add(("warning", "Has arcs in the XZ/YZ planes (G18/G19) - scaling is disabled for this file."))

    info = {"units": units, "cut": cut.to_dict(), "all": every.to_dict(), "can_scale": not has_g18_19_arcs}

    to_mm = 25.4 if units == "inch" else 1.0
    for a in AXES:
        size = info["all"]["size"][a]
        if size is not None and size * to_mm > MACHINE_TRAVEL_MM[a]:
            notices.add((
                "warning",
                f"{a} travel is {size * to_mm:.1f} mm - more than the TTC450's {MACHINE_TRAVEL_MM[a]:.0f} mm.",
            ))

    info["notices"] = sorted(notices, key=lambda n: (n[0] != "warning", n[1]))
    return info


def get_toolpath(gcode):
    """XY polylines for previewing: [(kind, [(x, y), ...]), ...].

    kind is "cut" (tool on, feed move) or "travel" (rapids / laser-off moves).
    """
    polylines = []
    for _, state, move in _simulate(gcode):
        if move is None:
            continue
        s, e = move["start"], move["end"]
        if None in (s["X"], s["Y"], e["X"], e["Y"]):
            continue
        if move["arc"]:
            pts = _arc_polyline(s, e, move["words"], state.plane, move["arc"] == "cw")
        elif (s["X"], s["Y"]) == (e["X"], e["Y"]):
            continue  # Z-only move
        else:
            pts = [(e["X"], e["Y"])]
        kind = "cut" if move["cutting"] else "travel"
        if polylines and polylines[-1][0] == kind and polylines[-1][1][-1] == (s["X"], s["Y"]):
            polylines[-1][1].extend(pts)
        else:
            polylines.append((kind, [(s["X"], s["Y"])] + pts))
    return polylines


# --------------------------------------------------------------------------- #
# Feed rate (F) and spindle speed / laser power (S)
# --------------------------------------------------------------------------- #
_FS_RE = re.compile(r"([FSfs])(\s*)(" + _NUM + r")")
_G0_RE = re.compile(r"([Gg])(\s*)(0+)(?:\.0*)?(?![\d.])")


def _move_length(move, plane):
    s, e = move["start"], move["end"]
    if move["arc"]:
        geo = _arc_geometry(s, e, move["words"], plane, move["arc"] == "cw")
        if geo is not None:
            lin = _PLANES[plane][2]
            dl = e[lin] - s[lin] if None not in (s[lin], e[lin]) else 0.0
            return math.hypot(geo[2] * geo[4], dl)
    return math.sqrt(sum((e[a] - s[a]) ** 2 for a in AXES if None not in (s[a], e[a])))


def get_speed_info(gcode):
    """Usage of every feed rate and S value, grouped by what the machine is doing.

    Returns {
      "work":  [row, ...]   feed (F) values of feed moves with the tool ON,
      "idle":  [row, ...]   feed (F) values of feed moves with the tool OFF / S0,
      "power": [row, ...]   non-zero S values used by the cutting moves,
      "rapids": {"moves", "length"}   G0 moves (always at the machine max rate),
      "no_feed": int        feed moves before any F was set,
      "inverse_time": bool  G93 used (feed editing is disabled),
      "laser": bool         best guess: M4 used, or no Z moves at all,
    }
    row = {"value", "moves", "length", "plunges"}; rows sorted by value.
    `length` is in file units; "plunges" counts Z-only moves.
    """
    groups = {"work": {}, "idle": {}, "power": {}}
    rapids = {"moves": 0, "length": 0.0}
    no_feed = 0
    inverse_time = used_m4 = has_z = False

    def add(group, value, length, plunge):
        row = groups[group].setdefault(value, {"value": value, "moves": 0, "length": 0.0, "plunges": 0})
        row["moves"] += 1
        row["length"] += length
        row["plunges"] += plunge

    for _, state, move in _simulate(gcode):
        inverse_time |= state.inverse_time
        used_m4 |= state.used_m4
        if move is None or move["kind"] is None:
            continue
        s, e = move["start"], move["end"]
        if "Z" in move["words"]:
            has_z = True
        length = _move_length(move, state.plane)
        if move["kind"] == "rapid":
            rapids["moves"] += 1
            rapids["length"] += length
            continue
        plunge = int(s["X"] == e["X"] and s["Y"] == e["Y"] and s["Z"] != e["Z"])
        if state.f is None:
            no_feed += 1
        else:
            add(move["kind"], state.f, length, plunge)
        if move["kind"] == "work" and state.s is not None:
            add("power", state.s, length, plunge)

    return {
        **{k: [v[key] for key in sorted(v)] for k, v in groups.items()},
        "rapids": rapids,
        "no_feed": no_feed,
        "inverse_time": inverse_time,
        "laser": used_m4 or not has_z,
    }


def _append_words(segments, new_words):
    """Append words (e.g. ["F1000", "S0"]) after the last code of the line."""
    for i in range(len(segments) - 1, -1, -1):
        is_code, text = segments[i]
        if is_code and text.strip():
            core = text.rstrip()
            sep = "" if re.search(r"\d[A-Za-z]", core) else " "  # keep "G1X10F800" style
            segments[i] = (True, core + "".join(sep + w for w in new_words) + text[len(core):])
            return segments
    return segments


def _prepend_word(segments, word):
    for i, (is_code, text) in enumerate(segments):
        if is_code and text.strip():
            lead = text[: len(text) - len(text.lstrip())]
            rest = text.lstrip()
            sep = "" if re.search(r"\d[A-Za-z]", rest) else " "
            segments[i] = (True, lead + word + sep + rest)
            return segments
    return segments


def apply_speeds(gcode, work_feed=None, idle_feed=None, power=None, rapid_feed=None, laser=False):
    """Change feed rates and S values.

    work_feed / idle_feed: {old F: new F} for feed moves (G1/G2/G3) with the
        tool on / off. The same F can be mapped differently in each group.
    power: {old S: new S} applied to every non-zero S word.
    rapid_feed: if set, G0 moves become G1 at this feed (G0 itself can't be
        slowed down - it always runs at GRBL's $110/$111 max rate). With
        `laser` True and the laser on, those moves also get S0 so nothing burns.
        (Not done for a spindle: S0 would stop it.)

    F and S are modal, so F/S words are re-emitted wherever the edited value
    differs from what the machine would otherwise still be using. Everything
    else in the file is left untouched.
    """
    work_feed, idle_feed, power = dict(work_feed or {}), dict(idle_feed or {}), dict(power or {})
    for v in list(work_feed.values()) + list(idle_feed.values()) + ([rapid_feed] if rapid_feed is not None else []):
        if not math.isfinite(v) or v <= 0:
            raise ValueError("Feed rates must be greater than 0.")
    for v in power.values():
        if not math.isfinite(v) or v < 0:
            raise ValueError("Spindle speed / laser power can't be negative.")
    power.pop(0.0, None)  # S0 = off, always stays 0
    changes_feed = any(k != v for k, v in list(work_feed.items()) + list(idle_feed.items())) or rapid_feed is not None

    # Kind of the next feed move after each line, so a stand-alone "F3000" line
    # gets the value of the move it is setting up (avoids redundant F words).
    kinds = [_move_kind(g, w, st) for _, _, _, g, w, st in _walk(gcode)]
    next_feed = [None] * (len(kinds) + 1)
    for i in range(len(kinds) - 1, -1, -1):
        next_feed[i] = kinds[i] if kinds[i] in ("work", "idle") else next_feed[i + 1]

    out = []
    out_f = out_s = out_motion = None  # what the machine uses after the edited lines
    for idx, (body, ending, segments, gcodes, words, state) in enumerate(_walk(gcode)):
        if state.inverse_time and changes_feed:
            raise ValueError("This file uses inverse-time feed (G93); feed rates can't be edited.")
        kind = _move_kind(gcodes, words, state)
        convert = kind == "rapid" and rapid_feed is not None
        feed_line = kind in ("work", "idle") or convert
        laser_off = convert and laser and state.spindle_on is not False

        desired_f = desired_s = None
        if feed_line:
            if convert:
                desired_f = rapid_feed
            elif state.f is not None:
                desired_f = (work_feed if kind == "work" else idle_feed).get(state.f, state.f)
            if laser_off:
                desired_s = 0.0
            elif state.s is not None:
                desired_s = power.get(state.s, state.s)

        line_f = line_s = None

        def repl(m):
            nonlocal line_f, line_s
            letter, value = m.group(1).upper(), float(m.group(3))
            if letter == "F":
                if feed_line:
                    new = desired_f if desired_f is not None else value
                elif kind is None and next_feed[idx]:  # F on a line that doesn't move
                    new = (work_feed if next_feed[idx] == "work" else idle_feed).get(value, value)
                else:
                    new = value
                line_f = new
            else:
                new = 0.0 if laser_off else power.get(value, value)
                line_s = new
            return m.group(0) if new == value else f"{m.group(1)}{m.group(2)}{_fmt(new)}"

        segs = [(c, _FS_RE.sub(repl, t) if c else t) for c, t in segments]

        if convert:
            replaced = False

            def g0(m):
                nonlocal replaced
                replaced = True
                return f"{m.group(1)}{m.group(2)}{'0' * (len(m.group(3)) - 1)}1"

            segs = [(c, _G0_RE.sub(g0, t) if c else t) for c, t in segs]
            if not replaced and out_motion != "1":
                segs = _prepend_word(segs, "G1")

        extra = []
        if feed_line and line_f is None and desired_f is not None and desired_f != out_f:
            extra.append("F" + _fmt(desired_f))
            line_f = desired_f
        if feed_line and line_s is None and desired_s is not None and desired_s != out_s:
            extra.append("S" + _fmt(desired_s))
            line_s = desired_s
        if extra:
            segs = _append_words(segs, extra)

        if line_f is not None:
            out_f = line_f
        if line_s is not None:
            out_s = line_s
        if convert:
            out_motion = "1"
        elif gcodes & MOTION_GCODES:
            out_motion = state.motion
        out.append("".join(t for _, t in segs) + ending)

    return "".join(out)


def alignment_box(info):
    """Box used for positioning/scaling: the cut area if any, else all moves."""
    if info["cut"]["min"]["X"] is not None or info["cut"]["min"]["Y"] is not None:
        return info["cut"]
    return info["all"]


def get_hash(content):
    return hashlib.md5(content.encode("utf-8")).hexdigest()
