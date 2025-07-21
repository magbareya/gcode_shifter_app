import streamlit as st
from utils import *

st.set_page_config(layout="wide")

# Initialize session state for modified content and click counter
if "output_gcode" not in st.session_state:
    st.session_state.output_gcode = ""
if "gcode_data" not in st.session_state:
    st.session_state.gcode_data = {}
if "shift_x" not in st.session_state:
    st.session_state.shift_x = 0.0
if "shift_y" not in st.session_state:
    st.session_state.shift_y = 0.0
if "shift_z" not in st.session_state:
    st.session_state.shift_z = 0.0
if "apply_count" not in st.session_state:
    st.session_state.apply_count = 0

# Title
st.title("Edit GCode files")

# Layout with two columns
col1, col2 = st.columns(2)

with col1:
    st.header("Editor1: Original File Content")
    uploaded_file = st.file_uploader("Upload a gcode file", type=["txt", 'nc', 'gcode'])
    if uploaded_file is not None:
        file_content = uploaded_file.read().decode("utf-8")
        st.session_state.output_gcode = file_content
    else:
        file_content = ""
    st.text_area("Original File Content", value=file_content, height=300, disabled=True)

    st.subheader("Shift data")
    shift_col_x, shift_col_y, shift_col_z = st.columns([1, 1, 1])
    with shift_col_x:
        st.number_input("X:", step=0.1, format="%.2f", key="shift_x")
        # st.session_state.shift_x = st.number_input("X:", step=0.1, format="%.2f", key="shift_x")
    with shift_col_y:
        st.number_input("Y:", step=0.1, format="%.2f", key="shift_y")
        # st.session_state.shift_y = st.number_input("Y:", step=0.1, format="%.2f", key="shift_y")
    with shift_col_z:
        st.number_input("Z:", step=0.1, format="%.2f", key="shift_z")
        # st.session_state.shift_z = st.number_input("Z:", step=0.1, format="%.2f", key="shift_z")

    if st.button("Apply"):
        shifted_gcode = shift_gcode(st.session_state.output_gcode, st.session_state.shift_x, st.session_state.shift_y, st.session_state.shift_z)
        gcode_data = get_max_min_xyz(shifted_gcode.split('\n'))
        st.session_state.output_gcode = shifted_gcode
        st.session_state.gcode_data = gcode_data
        st.success("Output updated!")

with col2:
    st.header("Output: Modified Content")
    st.download_button(label="Save file", data=st.session_state.output_gcode.encode("utf-8"), file_name="shifted.gcode", mime="text/plain")
    st.text_area("Result", value=st.session_state.output_gcode, height=480, disabled=True)
    st.write(st.session_state.gcode_data)
