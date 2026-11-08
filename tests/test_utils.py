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


def test_full_circle_without_endpoint():
    from utils import get_toolpath
    g = "G0 X10 Y0\nG2 I-10 J0\n"
    info = get_gcode_info(g)
    assert math.isclose(info["cut"]["min"]["X"], -10)
    assert math.isclose(info["cut"]["max"]["Y"], 10)
    assert len(get_toolpath(g)[0][1]) > 30


def test_inch_header_does_not_imply_mixed_units():
    info = get_gcode_info("; header\n%\nG20\nG0 X1 Y1\nG1 X2 Y2\n")
    assert info["units"] == "inch"
    assert not any("Switches" in text for _, text in info["notices"])


def test_special_blocks_update_or_invalidate_position():
    from utils import get_toolpath
    g = "G0 X10 Y10\nG92 X0 Y0\nG91 G1 X1 Y1\n"
    assert get_gcode_info(g)["cut"]["max"]["X"] == 1
    for block in ("G53 G0 X0 Y0", "G28", "G30", "G10 L2 P1 X5", "G55"):
        g = "G0 X10 Y10\n" + block + "\nG91 G1 X1 Y1\n"
        assert get_toolpath(g) == [], block
        assert get_gcode_info(g)["cut"]["min"]["X"] is None, block


def test_scale_nonfinite_and_non_xy_full_circles():
    for factor in (float("nan"), float("inf"), -float("inf")):
        assert _raises(lambda: scale_gcode("G1 X1", factor))
    assert _raises(lambda: scale_gcode("G18 G0 X0 Z0\nG2 K5", 2))
    assert not get_gcode_info("G18 G0 X0 Z0\nG2 K5")["can_scale"]


def test_scale_preserves_numbers_that_do_not_change():
    g = "G0 X1.123456 Y0.00000\nG2 X2.123456 I0.500000 J0.00000\n"
    assert scale_gcode(g, 1) == g
    assert "Y0.00000" in scale_gcode(g, 2)


# --------------------------------------------------------------------------- #
# Feed rate / power
# --------------------------------------------------------------------------- #
from utils import apply_speeds, get_speed_info  # noqa: E402

CNC_FEEDS = """G90 G21
M3 S12000
G0 Z5
G0 X0 Y0
G1 Z-1 F300
G1 X10 F800 ; cut
X20
G0 Z5
M5
G1 X0 Y0 F800
"""


def test_speed_info_groups_work_idle_rapid_and_power():
    info = get_speed_info(CNC_FEEDS)
    work = {r["value"]: r for r in info["work"]}
    assert set(work) == {300, 800}
    assert work[300]["plunges"] == 1 and work[800]["moves"] == 2
    assert math.isclose(work[800]["length"], 20)
    assert [r["value"] for r in info["idle"]] == [800]
    assert info["rapids"]["moves"] == 3
    assert [r["value"] for r in info["power"]] == [12000]
    assert not info["laser"]


def test_same_feed_mapped_differently_when_working_and_idle():
    out = apply_speeds(CNC_FEEDS, work_feed={800: 1000}).splitlines()
    assert out[5] == "G1 X10 F1000 ; cut"
    assert out[6] == "X20"                       # modal - already 1000
    assert out[9] == "G1 X0 Y0 F800"             # idle move keeps 800
    out = apply_speeds(CNC_FEEDS, idle_feed={800: 2000}).splitlines()
    assert out[5] == "G1 X10 F800 ; cut" and out[9] == "G1 X0 Y0 F2000"


def test_modal_feed_is_reemitted_when_switching_between_work_and_idle():
    g = "M4 S0\nG0 X0 Y0\nG1 X5 F3000 S0\nG1 X10 S500\nG1 X15 S0\n"
    out = apply_speeds(g, work_feed={3000: 1500}).splitlines()
    assert out[2] == "G1 X5 F3000 S0"
    assert out[3] == "G1 X10 S500 F1500"
    assert out[4] == "G1 X15 S0 F3000"
    assert get_speed_info("\n".join(out))["work"][0]["value"] == 1500


def test_power_map_and_no_change_is_identity():
    g = "M3 S1000\nG1X1F100S800\nG1 X2 S0\n"
    assert apply_speeds(g) == g
    assert apply_speeds(g, power={1000: 500, 800: 400, 0: 50}) == "M3 S500\nG1X1F100S400\nG1 X2 S0\n"


def test_rapid_limit_laser_turns_beam_off_and_restores():
    g = "M4 S500 F1000\nG0 X10\nG1 X20\nG00 X0\n"
    out = apply_speeds(g, rapid_feed=3000, laser=True)
    assert out == "M4 S500 F1000\nG1 X10 F3000 S0\nG1 X20 F1000 S500\nG01 X0 F3000 S0\n"


def test_rapid_limit_cnc_keeps_spindle_and_handles_modal_g0():
    g = "M3 S9000\nG0 Z5\nX10 Y10\nG53 G0 Z-1\nX0\nG1 Z-1 F200\n"
    out = apply_speeds(g, rapid_feed=2000, laser=False).splitlines()
    assert out[1] == "G1 Z5 F2000"
    assert out[2] == "X10 Y10"                   # modal, already G1 at F2000
    assert out[3] == "G53 G0 Z-1"                # machine move untouched
    assert out[4] == "G1 X0"                     # modal G0 again -> needs G1
    assert out[5] == "G1 Z-1 F200"


def test_speeds_reject_bad_values_and_inverse_time():
    assert _raises(lambda: apply_speeds("G1 X1 F100", work_feed={100: 0}))
    assert _raises(lambda: apply_speeds("G1 X1 F100", power={100: -1}))
    assert _raises(lambda: apply_speeds("G93 G1 X1 F2", work_feed={2: 3}))


def test_standalone_feed_line_takes_value_of_the_next_move():
    g = "M3 S1000\nG1 F3000.000\nG3 X10 Y0 I5 J0\nG1 X20 S0\n"
    out = apply_speeds(g, work_feed={3000: 2400}).splitlines()
    assert out[1] == "G1 F2400"
    assert out[2] == "G3 X10 Y0 I5 J0"           # no redundant F
    assert out[3] == "G1 X20 S0 F3000"           # idle move restores its own feed
