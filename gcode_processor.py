import os

import pandas as pd
import streamlit as st

from utils import AXES, alignment_box, get_gcode_info, get_hash, scale_gcode, shift_gcode

st.set_page_config(layout="wide")

defaults = {
    "file_hash": None,
    "original_gcode": "",
    "output_gcode": "",
    "gcode_info": None,
    "total_shift": {"X": 0.0, "Y": 0.0, "Z": 0.0},
    "shift_x": 0.0,
    "shift_y": 0.0,
    "shift_z": 0.0,
    "include_z": False,
    "total_scale": 1.0,
    "scale_mode": "Percent",
    "scale_percent": 100.0,
    "scale_target": 100.0,
    "scale_anchor": "Center",
}
for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


def set_output(gcode):
    st.session_state.output_gcode = gcode
    st.session_state.gcode_info = get_gcode_info(gcode)


def apply_shift(dx, dy, dz, message):
    set_output(shift_gcode(st.session_state.output_gcode, dx, dy, dz))
    total = st.session_state.total_shift
    total["X"] += dx
    total["Y"] += dy
    total["Z"] += dz
    st.success(f"{message}  (ΔX={dx:+.3f}, ΔY={dy:+.3f}, ΔZ={dz:+.3f})")


def target_shift(reference):
    """Shift that moves `reference` (min/mid point) onto the entered X/Y(/Z)."""
    box = alignment_box(st.session_state.gcode_info)[reference]
    entered = {"X": st.session_state.shift_x, "Y": st.session_state.shift_y, "Z": st.session_state.shift_z}
    axes = AXES if st.session_state.include_z else ("X", "Y")
    return [
        (entered[a] - box[a]) if a in axes and box[a] is not None else 0.0
        for a in AXES
    ]


st.title("Edit GCode files")
col1, col2 = st.columns(2)

with col1:
    st.header("Original file")
    uploaded_file = st.file_uploader("Upload a gcode file", type=["txt", "nc", "gcode", "ngc", "tap", "gc"])

    if uploaded_file is not None:
        content = uploaded_file.getvalue().decode("utf-8-sig", errors="replace")
        content_hash = get_hash(content)
        if content_hash != st.session_state.file_hash:  # new file -> reset
            st.session_state.file_hash = content_hash
            st.session_state.original_gcode = content
            st.session_state.total_shift = {"X": 0.0, "Y": 0.0, "Z": 0.0}
            st.session_state.total_scale = 1.0
            set_output(content)
    else:
        st.session_state.file_hash = None
        st.session_state.original_gcode = ""
        st.session_state.output_gcode = ""
        st.session_state.gcode_info = None
        st.session_state.total_shift = {"X": 0.0, "Y": 0.0, "Z": 0.0}
        st.session_state.total_scale = 1.0

    no_file = st.session_state.gcode_info is None
    st.text_area("Original File Content", value=st.session_state.original_gcode, height=300, disabled=True)

    b1, b2 = st.columns(2)
    with b1:
        if st.button("Move to XY 0,0", disabled=no_file, help="Put the lower-left corner of the cut/engraved area at X0 Y0"):
            box = alignment_box(st.session_state.gcode_info)["min"]
            apply_shift(-(box["X"] or 0.0), -(box["Y"] or 0.0), 0.0, "Moved to XY 0,0.")
    with b2:
        if st.button("Revert Output", disabled=no_file):
            set_output(st.session_state.original_gcode)
            st.session_state.total_shift = {"X": 0.0, "Y": 0.0, "Z": 0.0}
            st.session_state.total_scale = 1.0
            st.success("Output reverted to original content!")

    shift_col_x, shift_col_y, shift_col_z = st.columns(3)
    with shift_col_x:
        st.number_input("X:", step=0.1, format="%.3f", key="shift_x")
    with shift_col_y:
        st.number_input("Y:", step=0.1, format="%.3f", key="shift_y")
    with shift_col_z:
        st.number_input("Z:", step=0.1, format="%.3f", key="shift_z")
    st.checkbox(
        "Apply Z in 'Set Min' / 'Set Mid'",
        key="include_z",
        help="Off by default: changing Z changes cut depth (CNC) or focus (laser).",
    )

    b3, b4, b5 = st.columns(3)
    with b3:
        if st.button("Shift GCode", disabled=no_file, help="Add X/Y/Z to every absolute coordinate"):
            apply_shift(st.session_state.shift_x, st.session_state.shift_y, st.session_state.shift_z, "Shifted.")
    with b4:
        if st.button("Set Min to values", disabled=no_file, help="Move the min corner onto X/Y(/Z)"):
            apply_shift(*target_shift("min"), "Min set to given values.")
    with b5:
        if st.button("Set Mid to values", disabled=no_file, help="Move the centre onto X/Y(/Z)"):
            apply_shift(*target_shift("mid"), "Mid set to given values.")

    st.subheader("Scale (keeps aspect ratio)")
    sc1, sc2 = st.columns(2)
    with sc1:
        st.radio("Scale by", ["Percent", "Target width (X)", "Target height (Y)"], key="scale_mode")
    with sc2:
        st.radio(
            "Fixed point",
            ["Center", "Min corner (lower-left)"],
            key="scale_anchor",
            help="This point of the cut area stays in place while scaling.",
        )

    factor = None
    box = None if no_file else alignment_box(st.session_state.gcode_info)
    if st.session_state.scale_mode == "Percent":
        st.number_input("Scale %", min_value=0.1, step=5.0, format="%.2f", key="scale_percent")
        factor = st.session_state.scale_percent / 100.0
    elif box is not None:
        axis = "X" if st.session_state.scale_mode.startswith("Target width") else "Y"
        st.number_input(f"New {axis} size", min_value=0.001, step=1.0, format="%.3f", key="scale_target")
        current = box["size"][axis]
        if current:
            factor = st.session_state.scale_target / current
        else:
            st.info(f"The cut area has no {axis} extent - can't scale by {axis} size.")

    if box is not None and factor:
        sx, sy = box["size"]["X"], box["size"]["Y"]
        if sx is not None and sy is not None:
            st.caption(
                f"Factor {factor:.4f}  ·  size {sx:.3f} × {sy:.3f}  →  "
                f"{sx * factor:.3f} × {sy * factor:.3f} {st.session_state.gcode_info['units']}"
            )

    if st.button("Scale GCode", disabled=no_file or not factor):
        anchor_key = "mid" if st.session_state.scale_anchor == "Center" else "min"
        ref = box[anchor_key]
        try:
            set_output(scale_gcode(st.session_state.output_gcode, factor, ref["X"] or 0.0, ref["Y"] or 0.0))
            st.session_state.total_scale *= factor
            st.success(f"Scaled by {factor:.4f} around the {st.session_state.scale_anchor.lower()}.")
        except ValueError as e:
            st.error(str(e))

with col2:
    st.header("Output: Modified Content")
    if uploaded_file is not None:
        base, ext = os.path.splitext(uploaded_file.name)
        out_name = f"{base}_shifted{ext or '.gcode'}"
    else:
        out_name = "shifted.gcode"
    st.download_button(
        label="Save file",
        data=st.session_state.output_gcode.encode("utf-8"),
        file_name=out_name,
        mime="text/plain",
        disabled=no_file,
    )
    st.text_area("Result", value=st.session_state.output_gcode, height=480, disabled=True)

    info = st.session_state.gcode_info
    if info:
        t = st.session_state.total_shift
        st.caption(
            f"Units: {info['units']}  ·  Total scale vs original: "
            f"{st.session_state.total_scale * 100:.2f}%  ·  Shifts applied: "
            f"X {t['X']:+.3f}, Y {t['Y']:+.3f}, Z {t['Z']:+.3f}"
        )
        for title, key in (("Cut / engraved area (feed moves, tool on)", "cut"), ("All moves (incl. rapids & travel)", "all")):
            st.subheader(title)
            box = info[key]
            st.dataframe(
                pd.DataFrame({row: box[row] for row in ("min", "max", "mid", "size")}).T.style.format("{:.3f}", na_rep="-"),
                use_container_width=True,
            )
        for w in info["warnings"]:
            st.warning(w)
