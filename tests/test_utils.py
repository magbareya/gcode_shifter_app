import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import get_gcode_info, scale_gcode, shift_gcode  # noqa: E402

CNC = """; header comment
(Fusion style)
%
$H
G21 G90 G94
G17
M3 S12000
G0 Z5.000
G0 X-10.5 Y20.25
G1 Z-1.000 F300
G1 X100.123 Y20.25 F800 ; inline
X120 Y40
G91
G1 X5 Y5
G90
G53 G0 Z-2
G92 X0 Y0
G28 G91 Z0
G90
M5
M30
%
"""


def test_shift_preserves_non_motion_and_only_touches_absolute_targets():
    out = shift_gcode(CNC, 1, 2, 0).splitlines()
    src = CNC.splitlines()
    assert out[:8] == src[:8]                 # comments, %, $H, setup untouched
    assert out[8] == "G0 X-9.5 Y22.25"
    assert out[9] == "G1 Z-1.000 F300"        # Z shift is 0 -> untouched text
    assert out[10] == "G1 X101.123 Y22.25 F800 ; inline"
    assert out[11] == "X121 Y42"              # modal motion without G word
    assert out[13] == "G1 X5 Y5"              # G91 incremental - not shifted
    assert out[15] == "G53 G0 Z-2"            # machine coords - not shifted
    assert out[16] == "G92 X0 Y0"             # coordinate set - not shifted
    assert out[17] == "G28 G91 Z0"
    assert out[-1] == "%"


def test_shift_roundtrip_and_z():
    out = shift_gcode(CNC, 0, 0, -0.5)
    assert "G1 Z-1.5 F300" in out
    assert shift_gcode(out, 0, 0, 0.5).replace("Z5\n", "Z5.000\n").replace("Z-1 F", "Z-1.000 F") == CNC


def test_comment_with_axis_letters_untouched():
    assert shift_gcode("G1 X1 (move X10 Y10)\n", 1, 1) == "G1 X2 (move X10 Y10)\n"


def test_no_spaces_lowercase_and_crlf():
    assert shift_gcode("G1X10Y-2.5S300\r\n", 1, 1) == "G1X11Y-1.5S300\r\n"
    assert shift_gcode("g1 x10 y5\n", 1, 1) == "g1 x11 y6\n"


def test_info_cnc_bounds_and_g91_tracking():
    info = get_gcode_info(CNC)
    cut = info["cut"]
    assert cut["min"]["X"] == -10.5          # start of first feed move
    assert math.isclose(cut["max"]["X"], 125)  # 120 + incremental 5
    assert math.isclose(cut["max"]["Y"], 45)
    assert cut["min"]["Z"] == -1
    assert info["all"]["max"]["Z"] == 5
    assert info["units"] == "mm"


def test_negative_only_coordinates():
    info = get_gcode_info("G90\nG0 X-50 Y-50\nG1 X-10 Y-20 F100\n")
    assert info["cut"]["max"]["X"] == -10 and info["cut"]["min"]["X"] == -50


def test_arc_extents_ij_and_r():
    # quarter-ish CCW arc from (10,0) to (0,10) around origin passes through no
    # extra cardinal point; a semicircle G2 from (-10,0) to (10,0) passes (0,10)
    info = get_gcode_info("G0 X-10 Y0\nG2 X10 Y0 I10 J0 F100\n")
    assert math.isclose(info["cut"]["max"]["Y"], 10)
    info = get_gcode_info("G0 X-10 Y0\nG2 X10 Y0 R10 F100\n")
    assert math.isclose(info["cut"]["max"]["Y"], 10, abs_tol=1e-9)
    info = get_gcode_info("G0 X10 Y0\nG3 X10 Y0 I-10 J0 F100\n")  # full circle
    assert math.isclose(info["cut"]["min"]["X"], -10)
    assert math.isclose(info["cut"]["min"]["Y"], -10)


LASER = """G90
G21
M4 S0
G0 X5 Y5
G1 X3 S0 F6000
G1 X10 S800
G1 X20 S650
G1 X22 S0
G0 X0 Y0
M5
"""


def test_laser_overscan_and_return_home_excluded_from_cut_area():
    info = get_gcode_info(LASER)
    assert info["cut"]["min"]["X"] == 3 and info["cut"]["max"]["X"] == 20
    assert info["all"]["min"]["X"] == 0 and info["all"]["max"]["X"] == 22
    assert info["cut"]["min"]["Z"] is None   # no Z in a laser file


def test_unparseable_grbl_lines_do_not_crash():
    get_gcode_info("$H\n$X\n$$\nG0 X1\n")


def test_scale_around_center_keeps_center_and_ratio():
    g = "G90\nG0 X10 Y10 Z5\nG1 Z-1 F300\nG1 X30 Y20\nG2 X40 Y30 I10 J0\nG91\nG1 X2 Y-2\nG90\nG53 G0 Z-2\n"
    before = get_gcode_info(g)["cut"]
    mid = before["mid"]
    out = scale_gcode(g, 2.0, mid["X"], mid["Y"])
    after = get_gcode_info(out)["cut"]
    for a in ("X", "Y"):
        assert math.isclose(after["mid"][a], mid[a])
        assert math.isclose(after["size"][a], before["size"][a] * 2)
    assert after["min"]["Z"] == before["min"]["Z"]          # Z untouched
    lines = out.splitlines()
    assert lines[2] == "G1 Z-1 F300"
    assert "I20 J0" in lines[4]                              # arc offsets scaled
    assert lines[6] == "G1 X4 Y-4"                           # incremental scaled
    assert lines[8] == "G53 G0 Z-2"


def test_scale_r_arc_and_min_anchor():
    g = "G0 X0 Y0\nG2 X20 Y0 R10 F100\n"
    out = scale_gcode(g, 0.5, 0, 0)
    assert out == "G0 X0 Y0\nG2 X10 Y0 R5 F100\n"


def _raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def test_scale_rejects_bad_input():
    assert _raises(lambda: scale_gcode("G1 X1", 0))
    assert _raises(lambda: scale_gcode("G18 G0 X0 Z0\nG2 X10 Z0 I5 K0", 2))
