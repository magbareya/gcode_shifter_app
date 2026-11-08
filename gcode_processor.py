"""G-code Shifter - position and resize GRBL jobs (CNC router or laser).

Run with:  python -m streamlit run gcode_processor.py
"""

import math
import os

import altair as alt
import pandas as pd
import streamlit as st

from utils import alignment_box, get_gcode_info, get_hash, get_toolpath, scale_gcode, shift_gcode

st.set_page_config(page_title="G-code Shifter", page_icon="📐", layout="wide")


def _environment_problem():
    """Return a message if this Python can't run the app correctly, else None."""
    from importlib.metadata import version

    st_version = tuple(int(p) for p in st.__version__.split(".")[:2])
    if st_version < (1, 60):
        return f"Streamlit {st.__version__} is too old (needs 1.60+)."
    if version("protobuf") == "5.28.0":
        return "protobuf 5.28.0 has a memory bug that crashes Streamlit widgets."
    return None


_problem = _environment_problem()
if _problem:
    import sys

    st.error(f"**This app was started with the wrong Python.** {_problem}", icon="⛔")
    st.markdown(
        f"Running: `{sys.executable}`\n\n"
        "Close this and start the app with **`run.bat`** in the project folder "
        "(it uses the project's own `.venv`), or run:"
    )
    st.code(r".venv\Scripts\python -m streamlit run gcode_processor.py", language="powershell")
    st.stop()

alt.data_transformers.disable_max_rows()

MAX_HISTORY = 30
MAX_PREVIEW_POINTS = 40_000
H_OPTIONS = {"Left": "min", "Center": "mid", "Right": "max"}
V_OPTIONS = {"Bottom": "min", "Middle": "mid", "Top": "max"}
COLORS = {"Cut": "#2563eb", "Travel": "#9ca3af", "Original": "#f59e0b"}

DEFAULTS = {
    "file_hash": None,
    "file_name": "",
    "original": "",
    "output": "",
    "history": [],  # [{"label": str, "before": str}]
    "flash": None,
    "section": "Position",
    "out_name": "shifted.gcode",
    "pos_mode": "Place at",
    "pos_h": "Left",
    "pos_v": "Bottom",
    "pos_x": 0.0,
    "pos_y": 0.0,
    "mv_x": 0.0,
    "mv_y": 0.0,
    "sc_mode": "Percent",
    "sc_pct": 100.0,
    "sc_size": 100.0,
    "sc_h": "Center",
    "sc_v": "Middle",
    "z_mode": "Set deepest cut to",
    "z_val": 0.0,
    "z_confirm": False,
    "show_travel": True,
    "show_original": True,
}
for _k, _v in DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v
ss = st.session_state


# --------------------------------------------------------------------------- #
# Cached analysis
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False, max_entries=16)
def analyze(gcode):
    return get_gcode_info(gcode)


@st.cache_data(show_spinner=False, max_entries=16)
def toolpath(gcode):
    return get_toolpath(gcode)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def fmt(value, units="", digits=2):
    if value is None:
        return "—"
    return f"{value:,.{digits}f}{(' ' + units) if units else ''}"


def pick(value, options, fallback):
    """segmented_control returns None when the user deselects - fall back."""
    return value if value in options else fallback


def anchor_point(box, h, v):
    return box[H_OPTIONS[h]]["X"], box[V_OPTIONS[v]]["Y"]


def push(label, new_gcode):
    if new_gcode == ss.output:
        ss.flash = ("info", "Nothing changed.")
        return
    ss.history.append({"label": label, "before": ss.output})
    del ss.history[:-MAX_HISTORY]
    ss.output = new_gcode
    ss.flash = ("success", label)


def current_box():
    return alignment_box(analyze(ss.output))


# --------------------------------------------------------------------------- #
# Actions (run as widget callbacks, i.e. before the page re-renders)
# --------------------------------------------------------------------------- #
def act_place(h=None, v=None, x=None, y=None):
    h = h or pick(ss.pos_h, H_OPTIONS, "Left")
    v = v or pick(ss.pos_v, V_OPTIONS, "Bottom")
    tx = ss.pos_x if x is None else x
    ty = ss.pos_y if y is None else y
    ax, ay = anchor_point(current_box(), h, v)
    dx, dy = tx - (ax or 0.0), ty - (ay or 0.0)
    push(f"Placed {h.lower()}-{v.lower()} at X{tx:g} Y{ty:g}", shift_gcode(ss.output, dx, dy, 0.0))


def act_move():
    push(f"Moved by X{ss.mv_x:+g} Y{ss.mv_y:+g}", shift_gcode(ss.output, ss.mv_x, ss.mv_y, 0.0))


def scale_factor(box):
    mode = pick(ss.sc_mode, ("Percent", "Width", "Height"), "Percent")
    if mode == "Percent":
        return ss.sc_pct / 100.0
    current = box["size"]["X" if mode == "Width" else "Y"]
    return ss.sc_size / current if current else None


def act_scale():
    box = current_box()
    factor = scale_factor(box)
    if not factor:
        return
    h = pick(ss.sc_h, H_OPTIONS, "Center")
    v = pick(ss.sc_v, V_OPTIONS, "Middle")
    rx, ry = anchor_point(box, h, v)
    try:
        push(f"Scaled to {factor * 100:.2f}%", scale_gcode(ss.output, factor, rx or 0.0, ry or 0.0))
    except ValueError as e:
        ss.flash = ("error", str(e))


def act_scale_mode_changed():
    box = current_box()
    mode = pick(ss.sc_mode, ("Percent", "Width", "Height"), "Percent")
    if mode != "Percent":
        size = box["size"]["X" if mode == "Width" else "Y"]
        if size:
            ss.sc_size = round(size, 3)


def act_z():
    zmin = current_box()["min"]["Z"]
    mode = pick(ss.z_mode, ("Set deepest cut to", "Move Z by"), "Move Z by")
    dz = (ss.z_val - zmin) if mode == "Set deepest cut to" else ss.z_val
    push(f"Z shifted by {dz:+g}", shift_gcode(ss.output, 0.0, 0.0, dz))
    ss.z_confirm = False  # require a fresh confirmation for every Z change


def act_undo():
    if ss.history:
        step = ss.history.pop()
        ss.output = step["before"]
        ss.flash = ("info", f"Undid: {step['label']}")


def act_reset():
    ss.output = ss.original
    ss.history = []
    ss.flash = ("info", "Reset to the original file.")


# --------------------------------------------------------------------------- #
# Preview chart
# --------------------------------------------------------------------------- #
def polylines_df(polys, layer_names):
    """layer_names: {"cut": "Cut", "travel": "Travel"} - which kinds to keep."""
    selected = [(layer_names[k], pts) for k, pts in polys if k in layer_names]
    total = sum(len(p) for _, p in selected) or 1
    stride = max(1, math.ceil(total / MAX_PREVIEW_POINTS))
    rows = []
    for path_id, (layer, pts) in enumerate(selected):
        kept = pts[::stride]
        if kept[-1] != pts[-1]:
            kept.append(pts[-1])
        rows.extend((x, y, f"{layer}{path_id}", i, layer) for i, (x, y) in enumerate(kept))
    return pd.DataFrame(rows, columns=["x", "y", "path", "i", "layer"])


def preview_chart(df, box, marker, units, width=620):
    xs = list(df["x"]) + [0.0]
    ys = list(df["y"]) + [0.0]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    sx, sy = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    pad = 0.06 * max(sx, sy)
    x0, x1, y0, y1 = x0 - pad, x1 + pad, y0 - pad, y1 + pad
    sx, sy = x1 - x0, y1 - y0

    # Equal scale on both axes, height clamped to something sensible.
    height = width * sy / sx
    if height > 680:
        height = 680
        grow = (sy * width / height - sx) / 2
        x0, x1 = x0 - grow, x1 + grow
    elif height < 280:
        height = 280
        grow = (sx * height / width - sy) / 2
        y0, y1 = y0 - grow, y1 + grow

    x_enc = alt.X("x:Q", title=f"X ({units})", scale=alt.Scale(domain=[x0, x1], nice=False, zero=False))
    y_enc = alt.Y("y:Q", title=f"Y ({units})", scale=alt.Scale(domain=[y0, y1], nice=False, zero=False))
    layers_present = [l for l in ("Cut", "Travel", "Original") if l in set(df["layer"])]

    paths = (
        alt.Chart(df)
        .mark_line(strokeWidth=1.4, interpolate="linear")
        .encode(
            x=x_enc,
            y=y_enc,
            detail="path:N",
            order="i:Q",
            color=alt.Color(
                "layer:N",
                title=None,
                scale=alt.Scale(domain=layers_present, range=[COLORS[l] for l in layers_present]),
                legend=alt.Legend(orient="top"),
            ),
            strokeDash=alt.StrokeDash(
                "layer:N",
                legend=None,
                scale=alt.Scale(
                    domain=layers_present,
                    range=[{"Cut": [1, 0], "Travel": [4, 3], "Original": [2, 2]}[l] for l in layers_present],
                ),
            ),
            opacity=alt.condition(alt.datum.layer == "Original", alt.value(0.55), alt.value(1.0)),
        )
    )

    origin = pd.DataFrame({"x": [0.0], "y": [0.0], "label": ["0,0"]})
    axes = alt.layer(
        alt.Chart(origin).mark_rule(color="#ef4444", strokeWidth=1, opacity=0.6).encode(x="x:Q"),
        alt.Chart(origin).mark_rule(color="#ef4444", strokeWidth=1, opacity=0.6).encode(y="y:Q"),
        alt.Chart(origin).mark_text(align="left", dx=5, dy=-7, color="#ef4444", fontWeight="bold").encode(
            x="x:Q", y="y:Q", text="label:N"
        ),
    )

    layers = [axes, paths]
    if box["min"]["X"] is not None and box["min"]["Y"] is not None:
        rect = pd.DataFrame([{"x": box["min"]["X"], "x2": box["max"]["X"], "y": box["min"]["Y"], "y2": box["max"]["Y"]}])
        layers.append(
            alt.Chart(rect)
            .mark_rect(fillOpacity=0, stroke="#2563eb", strokeDash=[3, 3], strokeWidth=1, opacity=0.6)
            .encode(x="x:Q", x2="x2:Q", y="y:Q", y2="y2:Q")
        )
    if marker and None not in marker[:2]:
        mk = pd.DataFrame([{"x": marker[0], "y": marker[1], "label": marker[2]}])
        layers.append(
            alt.Chart(mk)
            .mark_point(shape="diamond", size=140, filled=True, color="#16a34a")
            .encode(x="x:Q", y="y:Q", tooltip=["label:N", "x:Q", "y:Q"])
        )

    return alt.layer(*layers).properties(width=width, height=height).interactive()


# --------------------------------------------------------------------------- #
# Sidebar: file in / file out / history
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("1 · Load")
    uploaded = st.file_uploader(
        "G-code file",
        type=["nc", "gcode", "ngc", "tap", "gc", "txt"],
        help="Any GRBL G-code: router (Fusion, Carbide, Easel…) or laser (LightBurn, LaserGRBL…).",
    )

    if uploaded is not None:
        raw = uploaded.getvalue()
        content = raw.decode("utf-8-sig", errors="replace")
        h = get_hash(content)
        if h != ss.file_hash:
            ss.file_hash = h
            ss.file_name = uploaded.name
            ss.original = content
            ss.output = content
            ss.history = []
            base, ext = os.path.splitext(uploaded.name)
            ss.out_name = f"{base}_edited{ext or '.gcode'}"
            if "�" in content:
                ss.flash = ("warning", "Some characters weren't valid UTF-8 and were replaced. Check comments in the output.")
    elif ss.file_hash is not None:
        for _k in ("file_hash", "file_name", "original", "output"):
            ss[_k] = DEFAULTS[_k]
        ss.history = []

    loaded = ss.file_hash is not None
    modified = loaded and ss.output != ss.original

    if loaded:
        st.caption(f"{ss.original.count(chr(10)) + 1:,} lines · {len(ss.original) / 1024:,.1f} KB")

        st.header("3 · Save")
        st.text_input("File name", key="out_name")
        st.download_button(
            "Download G-code",
            data=ss.output.encode("utf-8"),
            file_name=ss.out_name or "edited.gcode",
            mime="text/plain",
            type="primary" if modified else "secondary",
            icon=":material/download:",
            width="stretch",
        )
        if not modified:
            st.caption("No changes yet - this would download the original.")
        st.caption("Always run a frame / dry run before cutting or burning.")

        st.header("History")
        if ss.history:
            for i, step in enumerate(ss.history, 1):
                st.markdown(f"{i}. {step['label']}")
        else:
            st.caption("No edits yet.")
        u1, u2 = st.columns(2)
        u1.button("Undo", icon=":material/undo:", on_click=act_undo, disabled=not ss.history, width="stretch")
        u2.button("Reset", icon=":material/restart_alt:", on_click=act_reset, disabled=not modified, width="stretch")


# --------------------------------------------------------------------------- #
# Main area
# --------------------------------------------------------------------------- #
if ss.flash:
    level, msg = ss.flash
    icons = {"success": "✅", "info": "ℹ️", "warning": "⚠️", "error": "⛔"}
    st.toast(msg, icon=icons.get(level))
    if level in ("warning", "error"):
        getattr(st, level)(msg)
    ss.flash = None

st.title("G-code Shifter")

if not loaded:
    st.markdown("Position and resize GRBL jobs for a CNC router or laser without going back to your CAM software.")
    c1, c2, c3 = st.columns(3)
    with c1.container(border=True):
        st.markdown("**1 · Load**\n\nUpload a `.nc` / `.gcode` file in the sidebar.")
    with c2.container(border=True):
        st.markdown("**2 · Adjust**\n\nPlace it on your work zero, move it, or scale it. The preview updates as you go.")
    with c3.container(border=True):
        st.markdown("**3 · Save**\n\nDownload the edited file and run a frame / dry run first.")
    st.stop()

info = analyze(ss.output)
orig_info = analyze(ss.original)
units = info["units"]
box = alignment_box(info)
obox = alignment_box(orig_info)
has_z = box["min"]["Z"] is not None


# ---- Summary metrics ------------------------------------------------------- #
def delta(axis, key):
    a, b = box[key][axis], obox[key][axis]
    if a is None or b is None or abs(a - b) < 1e-9:
        return None
    return f"{a - b:+.2f}"


m1, m2, m3, m4 = st.columns(4)
m1.metric("Width (X)", fmt(box["size"]["X"], units), delta("X", "size"), delta_color="off")
m2.metric("Height (Y)", fmt(box["size"]["Y"], units), delta("Y", "size"), delta_color="off")
m3.metric(
    "Lower-left corner",
    f"{fmt(box['min']['X'])}, {fmt(box['min']['Y'])}",
    help="Where the cut/engraved area starts, relative to your work zero (X0 Y0).",
)
m4.metric(
    "Deepest cut (Z)",
    fmt(box["min"]["Z"], units) if has_z else "No Z",
    delta("Z", "min"),
    delta_color="off",
    help="Lowest Z of the cutting moves. Laser files usually have no Z.",
)

for level, text in info["notices"]:
    if level == "warning":
        st.warning(text, icon="⚠️")
infos = [t for lvl, t in info["notices"] if lvl == "info"]
if infos:
    with st.expander(f"File notes ({len(infos)})", icon=":material/info:"):
        for t in infos:
            st.markdown(f"- {t}")

# ---- Controls | Preview ------------------------------------------------------ #
left, right = st.columns([5, 7], gap="large")
marker = None

with left:
    st.subheader("2 · Adjust")
    SECTIONS = ["Position", "Scale", "Z · depth / focus"]
    section = pick(
        st.segmented_control("Section", SECTIONS, key="section", label_visibility="collapsed"),
        SECTIONS,
        "Position",
    )

    if section == "Position":
        q1, q2 = st.columns(2)
        q1.button(
            "Lower-left → 0,0",
            icon=":material/south_west:",
            on_click=act_place,
            kwargs={"h": "Left", "v": "Bottom", "x": 0.0, "y": 0.0},
            width="stretch",
            help="Most common: start the job at your work zero.",
        )
        q2.button(
            "Center → 0,0",
            icon=":material/center_focus_strong:",
            on_click=act_place,
            kwargs={"h": "Center", "v": "Middle", "x": 0.0, "y": 0.0},
            width="stretch",
            help="For when you zero the machine on the middle of the stock.",
        )
        st.divider()

        mode = pick(
            st.segmented_control("Mode", ["Place at", "Move by"], key="pos_mode", label_visibility="collapsed"),
            ("Place at", "Move by"),
            "Place at",
        )
        if mode == "Place at":
            a1, a2 = st.columns(2)
            a1.segmented_control("Horizontal point", list(H_OPTIONS), key="pos_h")
            a2.segmented_control("Vertical point", list(V_OPTIONS), key="pos_v")
            b1, b2 = st.columns(2)
            b1.number_input(f"to X ({units})", step=1.0, format="%.3f", key="pos_x")
            b2.number_input(f"to Y ({units})", step=1.0, format="%.3f", key="pos_y")
            h = pick(ss.pos_h, H_OPTIONS, "Left")
            v = pick(ss.pos_v, V_OPTIONS, "Bottom")
            ax, ay = anchor_point(box, h, v)
            marker = (ax, ay, f"{h} / {v}")
            if ax is not None and ay is not None:
                st.caption(f"The ◆ point moves by X {ss.pos_x - ax:+.3f}, Y {ss.pos_y - ay:+.3f} {units}.")
            st.button("Place job", type="primary", on_click=act_place, width="stretch")
        else:
            b1, b2 = st.columns(2)
            b1.number_input(f"ΔX ({units})", step=1.0, format="%.3f", key="mv_x")
            b2.number_input(f"ΔY ({units})", step=1.0, format="%.3f", key="mv_y")
            st.button(
                "Move job",
                type="primary",
                on_click=act_move,
                disabled=ss.mv_x == 0 and ss.mv_y == 0,
                width="stretch",
            )

    elif section == "Scale":
        if not info["can_scale"]:
            st.info("This file has arcs in the XZ/YZ planes, which can't be scaled here.")
        else:
            st.segmented_control(
                "Scale by", ["Percent", "Width", "Height"], key="sc_mode", on_change=act_scale_mode_changed
            )
            sc_mode = pick(ss.sc_mode, ("Percent", "Width", "Height"), "Percent")
            if sc_mode == "Percent":
                st.number_input("Scale (%)", min_value=0.1, step=5.0, format="%.2f", key="sc_pct")
            else:
                st.number_input(f"New {sc_mode.lower()} ({units})", min_value=0.001, step=1.0, format="%.3f", key="sc_size")
            a1, a2 = st.columns(2)
            a1.segmented_control("Fixed point · horizontal", list(H_OPTIONS), key="sc_h")
            a2.segmented_control("Fixed point · vertical", list(V_OPTIONS), key="sc_v")

            factor = scale_factor(box)
            sx, sy = box["size"]["X"], box["size"]["Y"]
            if factor and sx is not None and sy is not None:
                with st.container(border=True):
                    st.markdown(
                        f"**{fmt(sx)} × {fmt(sy)}** → **{fmt(sx * factor)} × {fmt(sy * factor)}** {units} "
                        f"&nbsp;·&nbsp; {factor * 100:.2f}% 🔒 ratio kept"
                    )
                ax, ay = anchor_point(box, pick(ss.sc_h, H_OPTIONS, "Center"), pick(ss.sc_v, V_OPTIONS, "Middle"))
                marker = (ax, ay, "Fixed point")
            st.button(
                "Scale job",
                type="primary",
                on_click=act_scale,
                disabled=not factor or abs(factor - 1) < 1e-9,
                width="stretch",
            )
            with st.expander("What changes when you scale", icon=":material/help:"):
                st.markdown(
                    "- **Scaled:** X/Y positions and arcs. **Not changed:** Z depth, feed rate, spindle speed / laser power.\n"
                    "- **CNC:** the bit doesn't scale. Paths offset by the bit radius come out slightly off size, "
                    "and pocket step-over changes. For exact parts, re-export from CAM.\n"
                    "- **Laser images:** line spacing scales too. Enlarging leaves gaps (lighter); shrinking "
                    "overlaps lines (darker). Vector outlines scale fine."
                )

    else:
        if not has_z:
            st.info("This file has no Z moves (typical for laser files). Nothing to adjust here.")
        else:
            st.caption(
                f"Cutting Z range: **{fmt(box['max']['Z'], units)}** (top) to **{fmt(box['min']['Z'], units)}** (deepest). "
                "Changing Z changes how deep the bit cuts (CNC) or the focus height (laser)."
            )
            z_mode = pick(
                st.segmented_control("Z mode", ["Set deepest cut to", "Move Z by"], key="z_mode"),
                ("Set deepest cut to", "Move Z by"),
                "Move Z by",
            )
            st.number_input(
                f"{'Deepest Z' if z_mode == 'Set deepest cut to' else 'ΔZ'} ({units})", step=0.1, format="%.3f", key="z_val"
            )
            dz = (ss.z_val - box["min"]["Z"]) if z_mode == "Set deepest cut to" else ss.z_val
            if abs(dz) > 1e-9:
                direction = "deeper" if dz < 0 else "shallower"
                (st.warning if dz < 0 else st.info)(
                    f"Every Z move (including safe height) goes **{abs(dz):.3f} {units} {direction}**."
                )
            st.checkbox("I understand this changes the cut depth", key="z_confirm")
            st.button(
                "Apply Z change",
                type="primary",
                on_click=act_z,
                disabled=not ss.z_confirm or abs(dz) < 1e-9,
                width="stretch",
            )

with right:
    t1, t2 = st.columns(2)
    t1.toggle("Show travel moves", key="show_travel", help="Rapids and laser-off moves (dashed).")
    t2.toggle("Compare with original", key="show_original", disabled=not modified)

    kinds = {"cut": "Cut"}
    if ss.show_travel:
        kinds["travel"] = "Travel"
    frames = [polylines_df(toolpath(ss.output), kinds)]
    if modified and ss.show_original:
        frames.insert(0, polylines_df(toolpath(ss.original), {"cut": "Original"}))
    df = pd.concat(frames, ignore_index=True)

    if df.empty:
        st.info("No XY moves found to preview.")
    else:
        st.altair_chart(preview_chart(df, box, marker, units), width="content")
        st.caption(
            "Scroll to zoom · drag to pan · double-click to reset. "
            "Red cross = work zero (X0 Y0) · ◆ = the point your current action uses."
        )

# ---- Code view ---------------------------------------------------------------- #
changed = sum(a != b for a, b in zip(ss.original.splitlines(), ss.output.splitlines()))
with st.expander(f"G-code · {changed:,} line(s) changed", icon=":material/code:"):
    c1, c2 = st.columns(2)
    c1.text_area("Original", ss.original, height=320, disabled=True)
    c2.text_area("Edited", ss.output, height=320, disabled=True)
