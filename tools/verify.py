#!/usr/bin/env python3
"""Numerical checks for the Skin Tone Compressor DCTL (dctl/SkinToneCompressor.dctl).

Run after ANY change to the DCTL, tools/skinmodel.py or tools/gen_matrices.py:
    python3 tools/verify.py
Peak memory ~1.0 GB (max RSS, 2D Jacobian grids), ~125-140 s (measured with /usr/bin/time -l, 2026-10-23).
Run one instance at a time (high memory use).
Mutation testing: SKINTONE_DCTL=<copy.dctl> python3 tools/verify.py (one instance at a time).
Exit code 1 on any failure; the last line is "ALL OK" otherwise.

Checks (all on the one DCTL file and its numpy model, tools/skinmodel.py):
  1. DCTL text: nothing at top level but the alpha tag, the UI lines, the known #defines and the
     expected functions; every preprocessor line is one of the known #defines; DEFINE_UI_PARAMS
     exactly the spec; DEFINE_DCTL_ALPHA_MODE_STRAIGHT once before the UI; every function
     signature as expected and every function body canonical (curves, dispatch, Oklab chain,
     scbrt, softplus, remap_hue, transform; mat_* rows parsed from the live code, comments
     stripped, equal the `// MAT` blocks); the Zone Hue Edge sigma is the same statement in both
     sites and, evaluated from the text, equals the model's; the only comparisons are the C > 0
     atan2 guard and UI-parameter / tolerance guards; the only min/max/clamp are the log floor,
     the two 0.99 strength clamps, the tanh-argument guard and UI-parameter clamps;
     parse_ui_defaults() keys == skinmodel.PARAMS; skinmodel.model() == pixel() bit-for-bit;
     the model's constants equal the DCTL literals, and pixel_core() equals the DCTL transform()
     statements transpiled to numpy on random parameter draws over the full UI ranges.
  2. Matrices: both blocks printed by tools/gen_matrices.py appear verbatim in the DCTL; every
     `// MAT` block equals the derivation; inverse
     pairs give I; OKLAB_M1/M2/M2_INV equal the published values; M1 * AP1_TO_XYZ equals the
     published ACES AP1 -> XYZ matrix through Bradford (independent of gen_matrices.py);
     DWG, AWG4 and Rec.709 equal the whitepaper / IEC matrices; det > 0; Oklab of the white.
  3. Oklab round trips: derived matrices; full code -> Oklab -> code per working space with
     the DCTL's matrices (exact and published M2^-1); the output form lin + (F(labn) - F(lab))
     cancels the round-trip bias.
  4. Working-space curves: round trips, strictly increasing, branches agree at the
     breakpoints, manufacturer reference values, Rec.709 / sRGB odd and the IEC sRGB step;
     every #define and the 12 curve function bodies equal the spec closed forms.
  5. ColorChecker dark / light skin through all six spaces: same Oklab L / C / h, equal to the
     independent derivation (catches a wrong CAT), hue near the skin line.
  6. Softplus L clamp of the tilts: strictly increasing, bounded, identity inside.
  7. Tilts: target bounds for every Tilt Pivot (Ct_eff within Ct e^+-1.5, hue within +-60 deg);
     default Ct_eff at the ColorChecker skin L within 10 % of the measured chroma.
  8. Hue remap: slope >= 1 - strength per side on the full circle, Zone Hue Range Yellow x Red
     x Hue Strength x Zone Hue Edge; smooth at d = 0 and at the seam d = +-pi; sigma continuous
     in the slider, periodic, in [0, 1]; model red width under Lips Protect.
  9. Chroma remap at the skin line over the full UI grid (Ct_eff of every tilt), continuous at
     C -> 0; negative controls: the linear and power pulls invert, tanh does not.
 10. Chroma remap with Chroma Lift, Lips Protect and Zone Hue Edge: g(th) properties; the sweep
     formula equals the model; slope of ln Cn vs ln C > 0 on the full grid.
 11. 2D (ln C, d) Jacobian det > 0 on the fine 2001 x 3601 grid (equal and asymmetric widths,
     Ct_eff extremes), also after the Mix blend in Cartesian Oklab; seam at d = +-pi.
 12. 2D Jacobian det > 0 with lips, lift and Zone Hue Edge {0, 0.25, 0.5, 1}; the det at the
     strongest point; negative control: the rejected separate lips kernel (Design A) folds.
 13. Zone alpha a = wField * kH: in [0, 1], continuous in h, L and C (C1 in C), periodic, 0 on
     the neutral axis, independent of Strength / Lift / Mix / Show Shift, with and without
     Zone Hue Edge, luma window and lips; Zone Luma Window factors.
 14. Show Shift: R, G in range, (0.5, 0.5, 0.5) at Mix 0, sign of the attractor, continuous and
     periodic in hue, equal to the actual move of labn at Mix 1 (lift, lips, edge, 6 spaces).
 15. Alpha out = a * input alpha with Output Zone Alpha on, input alpha with it off.
 16. Zone Hue Edge: negative control (the pure tanh blend without window has a second switch at
     the anti-target); kernel values that motivate it; anti-target smoothness <= 1.3 x Edge 0
     on the model and on both DCTL sigma statements.
 17. Defaults: effect on the ColorChecker skin (hue moves towards the tilted target without
     passing it, L unchanged, alpha in [0, 1]); hue slope and 2D Jacobian in absolute hue.
"""
import difflib
import os
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import gen_matrices as gm                     # noqa: E402  (derivation reused, not duplicated)
import skinmodel as sm                        # noqa: E402  (numpy model of the DCTL)
from skinmodel import (                       # noqa: E402
    AP0_AP1, CC, CC_FLOOR, CC_HICUT, CC_LOWCUT, CURVES, DI_A, DI_B, DI_C, DI_LIN_CUT, DI_LOG_CUT, DI_M, LC4_A,
    LC4_B, LC4_C, LC4_S, LC4_T, TWO_M15, TWO_M16, WS_MAT, WS_ORDER, cc_enc, cct_dec, cct_enc, di_enc, lc4_enc,
    softplus)

FAIL = []
NONFINITE = []                                 # swept arrays with NaN / inf (min / max reductions would hide them)


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        FAIL.append(msg)


def fin(arr, label):
    """returns arr; records `label` if any element is NaN or inf (checked at the end)"""
    if not np.all(np.isfinite(arr)):
        NONFINITE.append(label)
    return arr


# SKINTONE_DCTL=<path> points every check at another file (mutation testing)
DCTL_PATH = Path(os.environ["SKINTONE_DCTL"]) if os.environ.get("SKINTONE_DCTL") else ROOT / "dctl" / "SkinToneCompressor.dctl"
TEXT = DCTL_PATH.read_text(encoding="utf-8")
NAME = DCTL_PATH.name
print(f"info checks run on {DCTL_PATH}")
cc = CC                                        # ColorChecker AP0 values and AP0_AP1: skinmodel.py
ident = lambda v: v                            # noqa: E731


def strip_comments(src):
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


def norm(src):
    """Comments removed, whitespace collapsed to single spaces."""
    return re.sub(r"\s+", " ", strip_comments(src)).strip()


def func_body(text, name):
    """Raw text between the braces of `__DEVICE__ <type> name(...) {...}` (None if absent)."""
    m = re.search(r"__DEVICE__\s+\w+\s+" + re.escape(name) + r"\s*\([^)]*\)\s*\{", text)
    if not m:
        return None
    depth, i = 1, m.end()
    while i < len(text) and depth:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[m.end():i - 1] if depth == 0 else None


def calls_of(src, fn):
    """every `fn(...)` call in a normalised source string, with balanced parentheses"""
    out, i = [], 0
    while True:
        i = src.find(fn + "(", i)
        if i < 0:
            return out
        j, depth = i + len(fn) + 1, 1
        while depth and j < len(src):
            depth += {"(": 1, ")": -1}.get(src[j], 0)
            j += 1
        out.append(src[i:j])
        i += 1


def body_check(fn, want_stmts):
    """the normalised body of fn equals the canonical statements (diff printed on failure)"""
    got = norm(func_body(TEXT, fn) or "")
    want = " ".join(want_stmts)
    check(got == want, f"{NAME}: {fn}() body is canonical ({len(want)} chars)")
    if got != want:
        for line in difflib.unified_diff(want.split("; "), got.split("; "), "canonical", NAME, lineterm="", n=1):
            print("     " + line)


# =====================================================================
# 1. DCTL text
# =====================================================================
NEED = {f"{e}_TO_XYZ" for e in ("AP1", "DWG", "AWG4", "REC709")} | {f"XYZ_TO_{e}" for e in ("AP1", "DWG", "AWG4", "REC709")} \
       | {"OKLAB_M1", "OKLAB_M2", "OKLAB_M2_INV", "OKLAB_M1_INV"}
MATS, mat_errors = sm.parse_matrices(TEXT, NAME)
for e in mat_errors:
    check(False, e)
print(f"info {NAME}: parsed matrices {sorted(MATS)}")
check(set(MATS) == NEED, f"{NAME}: exactly the expected MAT blocks ({len(MATS)}/{len(NEED)})")
for missing in NEED - set(MATS):
    MATS[missing] = np.full((3, 3), np.nan)          # later checks FAIL cleanly instead of raising


def to_lab(rgb, mat="AP1"):
    return sm.to_lab(rgb, mat, MATS)


def from_lab(lab, mat="AP1", m2_inv=None):
    return sm.from_lab(lab, mat, MATS, m2_inv)


UI_SPEC = [
    "DEFINE_UI_PARAMS(workingSpace, Working Space, DCTLUI_COMBO_BOX, 0, { WS_ACESCCT, WS_ACESCC, WS_DWG, WS_LOGC4, "
    "WS_REC709, WS_SRGB }, { ACEScct, ACEScc, DaVinci Intermediate, ARRI LogC4, Rec.709 Gamma 2.4, sRGB })",
    "DEFINE_UI_PARAMS(targetHue, Target Hue deg, DCTLUI_SLIDER_FLOAT, 47.0, 0.0, 360.0, 0.1)",
    "DEFINE_UI_PARAMS(targetHueTilt, Target Hue Tilt vs Luma deg, DCTLUI_SLIDER_FLOAT, 12.0, -60.0, 60.0, 0.5)",
    "DEFINE_UI_PARAMS(targetChroma, Target Chroma, DCTLUI_SLIDER_FLOAT, 0.06, 0.01, 0.2, 0.001)",
    "DEFINE_UI_PARAMS(targetChromaTilt, Target Chroma Tilt vs Luma pct, DCTLUI_SLIDER_FLOAT, 60.0, -150.0, 150.0, 1.0)",
    "DEFINE_UI_PARAMS(tiltPivot, Tilt Pivot Luma, DCTLUI_SLIDER_FLOAT, 0.6, 0.2, 1.0, 0.01)",
    "DEFINE_UI_PARAMS(zoneHueYellow, Zone Hue Range Yellow deg, DCTLUI_SLIDER_FLOAT, 45.0, 5.0, 180.0, 0.1)",
    "DEFINE_UI_PARAMS(zoneHueRed, Zone Hue Range Red deg, DCTLUI_SLIDER_FLOAT, 45.0, 5.0, 180.0, 0.1)",
    "DEFINE_UI_PARAMS(zoneHueEdge, Zone Hue Edge, DCTLUI_SLIDER_FLOAT, 0.0, 0.0, 1.0, 0.01)",
    "DEFINE_UI_PARAMS(zoneChromaMin, Zone Chroma Min, DCTLUI_SLIDER_FLOAT, 0.025, 0.001, 0.1, 0.001)",
    "DEFINE_UI_PARAMS(zoneChromaMax, Zone Chroma Max, DCTLUI_SLIDER_FLOAT, 0.35, 0.05, 0.5, 0.005)",
    "DEFINE_UI_PARAMS(zoneLumaWindow, Zone Luma Window, DCTLUI_CHECK_BOX, 0)",
    "DEFINE_UI_PARAMS(zoneLumaMin, Zone Luma Min, DCTLUI_SLIDER_FLOAT, 0.1, 0.0, 0.8, 0.01)",
    "DEFINE_UI_PARAMS(zoneLumaMax, Zone Luma Max, DCTLUI_SLIDER_FLOAT, 1.1, 0.3, 1.5, 0.01)",
    "DEFINE_UI_PARAMS(hueStrength, Hue Strength, DCTLUI_SLIDER_FLOAT, 0.5, 0.0, 0.99, 0.01)",
    "DEFINE_UI_PARAMS(chromaStrength, Chroma Strength, DCTLUI_SLIDER_FLOAT, 0.3, 0.0, 0.99, 0.01)",
    "DEFINE_UI_PARAMS(chromaLift, Chroma Lift pct, DCTLUI_SLIDER_FLOAT, 100.0, 0.0, 100.0, 1.0)",
    "DEFINE_UI_PARAMS(chromaTolerance, Chroma Tolerance pct, DCTLUI_SLIDER_FLOAT, 30.0, 0.0, 100.0, 1.0)",
    "DEFINE_UI_PARAMS(lipsProtect, Lips Protect, DCTLUI_SLIDER_FLOAT, 0.0, 0.0, 1.0, 0.01)",
    "DEFINE_UI_PARAMS(lipsChromaMin, Lips Chroma Min, DCTLUI_SLIDER_FLOAT, 0.1, 0.03, 0.4, 0.005)",
    "DEFINE_UI_PARAMS(mix, Mix, DCTLUI_SLIDER_FLOAT, 1.0, 0.0, 1.0, 0.01)",
    "DEFINE_UI_PARAMS(outputAlpha, Output Zone Alpha, DCTLUI_CHECK_BOX, 1)",
    "DEFINE_UI_PARAMS(showShift, Show Shift, DCTLUI_CHECK_BOX, 0)",
]
ui_norm = lambda s: re.sub(r"\(\s*", "(", re.sub(r"\s*,\s*", ", ", re.sub(r"\s+", " ", s.strip())))   # noqa: E731
ui_got = [ui_norm(l) for l in TEXT.splitlines() if l.strip().startswith("DEFINE_UI_PARAMS")]
ui_want = [ui_norm(l) for l in UI_SPEC]
check(ui_got == ui_want, f"{NAME}: DEFINE_UI_PARAMS are exactly the spec ({len(ui_got)} lines, in order; labels, ranges "
                         f"and defaults)" + ("" if ui_got == ui_want else "\n     " + "\n     ".join(sorted(set(ui_got) ^ set(ui_want)))))
code = strip_comments(TEXT)
tag = [m.start() for m in re.finditer(r"^\s*DEFINE_DCTL_ALPHA_MODE_STRAIGHT\s*$", code, re.M)]
check(len(tag) == 1 and 0 <= tag[0] < code.find("DEFINE_UI_PARAMS") and "PREMULTIPLY" not in code,
      f"{NAME}: DEFINE_DCTL_ALPHA_MODE_STRAIGHT once, before the first DEFINE_UI_PARAMS, no PREMULTIPLY tag")
check(bool(re.search(r"__DEVICE__ float4 transform\(int p_Width, int p_Height, int p_X, int p_Y, "
                     r"float p_R, float p_G, float p_B, float p_A\)", TEXT)),
      f"{NAME}: transform() has the RGBA signature of the Resolve README (Transform DCTL with alpha)")
FN_RX = r"__DEVICE__\s+\w+\s+(\w+)\s*\("
FN_WANT = ["cct_to_lin", "lin_to_cct", "cc_to_lin", "lin_to_cc", "di_to_lin", "lin_to_di", "logc4_to_lin", "lin_to_logc4",
           "r709_to_lin", "lin_to_r709", "srgb_to_lin", "lin_to_srgb", "decode_log", "encode_log",
           "mat_ap1_to_xyz", "mat_xyz_to_ap1", "mat_dwg_to_xyz", "mat_xyz_to_dwg", "mat_awg4_to_xyz", "mat_xyz_to_awg4",
           "mat_rec709_to_xyz", "mat_xyz_to_rec709", "rgb_to_xyz", "xyz_to_rgb", "scbrt", "softplus",
           "mat_oklab_m1", "mat_oklab_m2", "mat_oklab_m2_inv", "mat_oklab_m1_inv", "xyz_to_oklab", "oklab_to_xyz",
           "rgb_to_oklab", "oklab_to_rgb", "remap_hue", "transform"]
fns = re.findall(FN_RX, TEXT)
check(fns == FN_WANT, f"{NAME}: the {len(FN_WANT)} expected __DEVICE__ functions, in order (found {len(fns)})"
      + ("" if fns == FN_WANT else f"\n     got:  {fns}"))
SIG_WANT = [f"__DEVICE__ float {f}(float x)" for f in FN_WANT[:12]] + [
    "__DEVICE__ float3 decode_log(float3 c, int ws)", "__DEVICE__ float3 encode_log(float3 c, int ws)"] + [
    f"__DEVICE__ float3 {f}(float3 c)" for f in FN_WANT[14:22]] + [
    "__DEVICE__ float3 rgb_to_xyz(float3 c, int ws)", "__DEVICE__ float3 xyz_to_rgb(float3 c, int ws)",
    "__DEVICE__ float scbrt(float x)", "__DEVICE__ float softplus(float x, float k)"] + [
    f"__DEVICE__ float3 {f}(float3 c)" for f in FN_WANT[26:30]] + [
    "__DEVICE__ float3 xyz_to_oklab(float3 c)", "__DEVICE__ float3 oklab_to_xyz(float3 lab)",
    "__DEVICE__ float3 rgb_to_oklab(float3 c, int ws)", "__DEVICE__ float3 oklab_to_rgb(float3 lab, int ws)",
    "__DEVICE__ float remap_hue(float h, float target, float wY, float wR, float s, float str)",
    "__DEVICE__ float4 transform(int p_Width, int p_Height, int p_X, int p_Y, float p_R, float p_G, float p_B, float p_A)"]
code = strip_comments(TEXT)
sigs = [re.sub(r"\s+", " ", m.group(0)) for m in re.finditer(r"__DEVICE__\s+\w+\s+\w+\s*\([^)]*\)", code)]
check(sigs == SIG_WANT, f"{NAME}: every __DEVICE__ signature as expected ({len(sigs)})"
      + ("" if sigs == SIG_WANT else "\n     " + "\n     ".join(sorted(set(sigs) ^ set(SIG_WANT)))))
# Preprocessor: every directive (also `# define`, `#undef`, `#if`...) must be one of the known #defines of
# a numeric literal; their values are checked in section 4.
KNOWN_DEFINES = {"DI_A", "DI_B", "DI_C", "DI_M", "DI_LIN_CUT", "DI_LOG_CUT", "LC4_A", "LC4_B", "LC4_C", "LC4_S", "LC4_T"}
DEF_RX = re.compile(r"[ \t]*#define[ \t]+(\w+)[ \t]+\(?[ \t]*[+-]?\d+\.\d+f[ \t]*\)?[ \t]*")
pp_lines = [l for l in code.splitlines() if re.match(r"[ \t]*(?:#|%:)", l)]
pp_names = [m.group(1) for m in map(DEF_RX.fullmatch, pp_lines) if m]
check(len(pp_names) == len(pp_lines) and sorted(pp_names) == sorted(KNOWN_DEFINES),
      f"{NAME}: the only preprocessor lines are the {len(KNOWN_DEFINES)} known numeric #defines, once each "
      f"({len(pp_lines)} directive lines)" + ("" if len(pp_names) == len(pp_lines) else
                                              "\n     " + "\n     ".join(l for l in pp_lines if not DEF_RX.fullmatch(l))))
# Top level: once the alpha tag, the UI lines, the #defines and the functions are removed, nothing is left.
rest = "\n".join(l for l in code.splitlines() if not (l.strip().startswith("DEFINE_UI_PARAMS(") or DEF_RX.fullmatch(l)
                                                       or l.strip() == "DEFINE_DCTL_ALPHA_MODE_STRAIGHT"))
for m in list(re.finditer(r"__DEVICE__\s+\w+\s+\w+\s*\([^)]*\)\s*\{", rest))[::-1]:
    depth, i = 1, m.end()
    while i < len(rest) and depth:
        depth += {"{": 1, "}": -1}.get(rest[i], 0)
        i += 1
    rest = rest[:m.start()] + rest[i:]
check(rest.strip() == "", f"{NAME}: no top-level code besides the alpha tag, the UI, the #defines and the functions"
      + ("" if rest.strip() == "" else f"\n     left: {rest.strip()[:300]!r}"))

# each `// MAT NAME` sits in the function of the matching name, and nowhere else
MAT_FUNC = {"mat_ap1_to_xyz": "AP1_TO_XYZ", "mat_xyz_to_ap1": "XYZ_TO_AP1",
            "mat_dwg_to_xyz": "DWG_TO_XYZ", "mat_xyz_to_dwg": "XYZ_TO_DWG",
            "mat_awg4_to_xyz": "AWG4_TO_XYZ", "mat_xyz_to_awg4": "XYZ_TO_AWG4",
            "mat_rec709_to_xyz": "REC709_TO_XYZ", "mat_xyz_to_rec709": "XYZ_TO_REC709",
            "mat_oklab_m1": "OKLAB_M1", "mat_oklab_m2": "OKLAB_M2",
            "mat_oklab_m2_inv": "OKLAB_M2_INV", "mat_oklab_m1_inv": "OKLAB_M1_INV"}
for fn, mname in MAT_FUNC.items():
    markers = re.findall(r"//\s*MAT\s+(\w+)", func_body(TEXT, fn) or "")
    check(markers == [mname], f"{NAME}: {fn}() holds exactly MAT {mname} (found {markers})")
    # the LIVE code (comments stripped) must be exactly `return make_float3(row, row, row);` with the
    # values of the `// MAT` block: a block commented out next to different live rows fails here
    live = norm(func_body(TEXT, fn) or "")
    term = r"([+-]?)(\d+\.\d+)f \* c\.x ([+-])(\d+\.\d+)f \* c\.y ([+-])(\d+\.\d+)f \* c\.z"
    ml = re.fullmatch(r"return make_float3\( " + term + ", " + term + ", " + term + r"\);", live)
    Ml = np.array([[(-1.0 if g[k] == "-" else 1.0) * float(g[k + 1]) for k in (0, 2, 4)]
                   for g in (ml.groups()[r * 6:r * 6 + 6] for r in range(3))]) if ml else None
    check(Ml is not None and np.array_equal(Ml, MATS.get(mname, np.full((3, 3), np.nan))),
          f"{NAME}: {fn}() live code is `return make_float3(3 rows)` equal to MAT {mname}"
          + ("" if ml else f"\n     got: {live[:300]}"))


def dispatch(fn, per_channel):
    """{WS_x or 'else': called function} for an if / else if / else chain on ws."""
    body = norm(func_body(TEXT, fn) or "")
    arms = re.findall(r"(?:else )?if \(ws == (WS_\w+)\) return ([^;]+);", body)
    last = re.findall(r"else return ([^;]+); *$", body)
    out = {}
    for ws_, expr in arms + [("else", e) for e in last]:
        if per_channel:
            m = re.fullmatch(r"make_float3\((\w+)\(c\.x\), (\w+)\(c\.y\), (\w+)\(c\.z\)\)", expr)
            out[ws_] = m.group(1) if m and m.group(1) == m.group(2) == m.group(3) else f"?{expr}"
        else:
            m = re.fullmatch(r"(\w+)\(c\)", expr)
            out[ws_] = m.group(1) if m else f"?{expr}"
    if body.count("return") != len(arms) + len(last):
        out["unparsed"] = body
    return out


EXPECT_DISPATCH = {
    "decode_log": {"WS_ACESCC": "cc_to_lin", "WS_DWG": "di_to_lin", "WS_LOGC4": "logc4_to_lin", "WS_REC709": "r709_to_lin",
                   "WS_SRGB": "srgb_to_lin", "else": "cct_to_lin"},
    "encode_log": {"WS_ACESCC": "lin_to_cc", "WS_DWG": "lin_to_di", "WS_LOGC4": "lin_to_logc4", "WS_REC709": "lin_to_r709",
                   "WS_SRGB": "lin_to_srgb", "else": "lin_to_cct"},
    "rgb_to_xyz": {"WS_DWG": "mat_dwg_to_xyz", "WS_LOGC4": "mat_awg4_to_xyz", "WS_REC709": "mat_rec709_to_xyz",
                   "WS_SRGB": "mat_rec709_to_xyz", "else": "mat_ap1_to_xyz"},
    "xyz_to_rgb": {"WS_DWG": "mat_xyz_to_dwg", "WS_LOGC4": "mat_xyz_to_awg4", "WS_REC709": "mat_xyz_to_rec709",
                   "WS_SRGB": "mat_xyz_to_rec709", "else": "mat_xyz_to_ap1"},
}
for fn, want in EXPECT_DISPATCH.items():
    got = dispatch(fn, fn.endswith("_log"))
    check(got == want, f"{NAME}: {fn}() dispatch {got}" + ("" if got == want else f" != {want}"))
    arms = [(ws_, f"make_float3({f_}(c.x), {f_}(c.y), {f_}(c.z))" if fn.endswith("_log") else f"{f_}(c)")
            for ws_, f_ in want.items()]
    canon = [("if" if k == 0 else "else if") + f" (ws == {ws_}) return {e};" for k, (ws_, e) in enumerate(arms[:-1])]
    body_check(fn, canon + [f"else return {arms[-1][1]};"])
# the combo enum order is the WS_ORDER the model uses
m_enum = re.search(r"DEFINE_UI_PARAMS\(workingSpace,[^{]*\{([^}]*)\}", TEXT)
enum_order = re.findall(r"WS_\w+", m_enum.group(1)) if m_enum else []
check(enum_order == ["WS_ACESCCT", "WS_ACESCC", "WS_DWG", "WS_LOGC4", "WS_REC709", "WS_SRGB"] and len(WS_ORDER) == 6,
      f"{NAME}: Working Space enum order {enum_order} matches skinmodel.WS_ORDER {WS_ORDER}")

# canonical bodies: Oklab chain and helpers, hue remap, transform (comments stripped, whitespace collapsed)
CHAIN_BODIES = {
    "xyz_to_oklab": ["float3 lms = mat_oklab_m1(c);", "lms = make_float3(scbrt(lms.x), scbrt(lms.y), scbrt(lms.z));",
                     "return mat_oklab_m2(lms);"],
    "oklab_to_xyz": ["float3 lms = mat_oklab_m2_inv(lab);",
                     "lms = make_float3(lms.x * lms.x * lms.x, lms.y * lms.y * lms.y, lms.z * lms.z * lms.z);",
                     "return mat_oklab_m1_inv(lms);"],
    "rgb_to_oklab": ["return xyz_to_oklab(rgb_to_xyz(c, ws));"],
    "oklab_to_rgb": ["return xyz_to_rgb(oklab_to_xyz(lab), ws);"],
    "scbrt": ["return _copysignf(_powf(_fabs(x), 1.0f / 3.0f), x);"],
    "softplus": ["return _fmaxf(x, 0.0f) + k * _logf(1.0f + _expf(-_fabs(x) / k));"],
}
for fn, want in CHAIN_BODIES.items():
    body_check(fn, want)
SIGMA = ("float sigma = (s > 0.0f) ? 0.5f * (1.0f + _sinf(d)) + 0.5f * (1.0f + _cosf(d)) * (0.5f * (1.0f + "
         "_tanhf(s * _sinf(d)) / _tanhf(s)) - 0.5f * (1.0f + _sinf(d))) : 0.5f * (1.0f + _sinf(d));")
sig_rh = re.search(r"__DEVICE__\s+float\s+remap_hue\s*\(([^)]*)\)", TEXT)
check(sig_rh is not None and re.sub(r"\s+", " ", sig_rh.group(1)).strip()
      == "float h, float target, float wY, float wR, float s, float str",
      f"{NAME}: remap_hue(h, target, wY, wR, s, str) signature")
body_check("remap_hue", [
    "float d = h - target;", "d = d - 6.283185307f * _round(d / 6.283185307f);", SIGMA,
    "float w = wR + (wY - wR) * sigma;", "float kappa = 1.0f / (w * w);",
    "float dn = d - str * _sinf(d) * _expf(kappa * (_cosf(d) - 1.0f));", "return target + dn;"])
body_check("transform", [
    "int ws = workingSpace;", "float3 lin = decode_log(make_float3(p_R, p_G, p_B), ws);",
    "float3 lab = rgb_to_oklab(lin, ws);", "float C = _sqrtf(lab.y * lab.y + lab.z * lab.z);",
    "float h = (C > 0.0f) ? _atan2f(lab.z, lab.y) : 0.0f;",
    # zone field over (L, C): knee, ceiling, softplus L clamp, luma window, lips chroma factor
    "float C2 = C * C;", "float k2 = zoneChromaMin * zoneChromaMin;", "float wKnee = (k2 > 0.0f) ? C2 / (C2 + k2) : 1.0f;",
    "float r4 = (C / zoneChromaMax);", "r4 = r4 * r4;", "r4 = r4 * r4;", "float wCeil = 1.0f / (1.0f + r4);",
    "float Lc = lab.x - softplus(lab.x - 1.2f, 0.05f) + softplus(-lab.x, 0.05f);",
    "float L8 = Lc * Lc;", "L8 = L8 * L8;", "L8 = L8 * L8;",
    "float m8 = zoneLumaMin * zoneLumaMin;", "m8 = m8 * m8;", "m8 = m8 * m8;",
    "float wLKnee = (m8 > 0.0f) ? L8 / (L8 + m8) : 1.0f;",
    "float rL = Lc / _fmaxf(zoneLumaMax, 0.01f);", "rL = rL * rL;", "rL = rL * rL;", "rL = rL * rL;",
    "float wLCeil = 1.0f / (1.0f + rL);", "float wL = zoneLumaWindow ? wLKnee * wLCeil : 1.0f;",
    "float rC = C / _fmaxf(lipsChromaMin, 0.001f);", "rC = rC * rC;", "float cL = 1.0f - 1.0f / (1.0f + rC);",
    "float wField = wKnee * wCeil * wL;", "float wgt = _fminf(hueStrength * wField, 0.99f);",
    # target line and hue kernel (the same width blend as remap_hue)
    "float target = (targetHue + targetHueTilt * (Lc - tiltPivot)) * 0.01745329252f;",
    "float wY = _fminf(_fmaxf(zoneHueYellow, 1.0f), 180.0f) * 0.01745329252f;",
    "float wR = _fminf(_fmaxf(zoneHueRed, 1.0f), 180.0f) * (1.0f - 0.9f * lipsProtect * cL) * 0.01745329252f;",
    "float d = h - target;", "d = d - 6.283185307f * _round(d / 6.283185307f);", "float s = 16.0f * zoneHueEdge;",
    SIGMA, "float w = wR + (wY - wR) * sigma;", "float kH = _expf((_cosf(d) - 1.0f) / (w * w));",
    "float wC = _fminf(chromaStrength * wField * kH, 0.99f);",
    "float a = wField * kH;", "float alphaOut = outputAlpha ? a * p_A : p_A;",
    "float hn = remap_hue(h, target, wY, wR, s, wgt);",
    # chroma remap: log domain, tolerance, tanh, Chroma Lift
    "float u = _logf(_fmaxf(C, 1e-12f) / targetChroma) - (targetChromaTilt * 0.01f) * (Lc - tiltPivot);",
    "float delta = _logf(1.0f + chromaTolerance * 0.01f);",
    "float f = (delta > 1e-4f) ? u - delta * _tanhf(_clampf(u / delta, -20.0f, 20.0f)) : u;",
    "float th = _tanhf(f);", "float lift = chromaLift * 0.01f;", "float xl = _fabs(th) / 0.05f;",
    "float lc = 0.05f * (xl + _logf(1.0f + _expf(-2.0f * xl)) - 0.6931471806f);",
    "float g = 0.5f * (1.0f + lift) * th + 0.5f * (1.0f - lift) * lc;", "float Cn = C * _expf(-wC * g);",
    # output: Mix in Oklab, bias-cancelling form, Show Shift, RGBA
    "float3 labn = make_float3(lab.x, Cn * _cosf(hn), Cn * _sinf(hn));", "labn = lab + (labn - lab) * mix;",
    "float3 outl = lin + (oklab_to_rgb(labn, ws) - oklab_to_rgb(lab, ws));",
    "float dh = hn - h;", "dh = dh - 6.283185307f * _round(dh / 6.283185307f);", "float dlnC = -wC * g;",
    "float3 shift = make_float3(0.5f + dh * 57.29577951f / 60.0f * mix, 0.5f + dlnC * mix, 0.5f);",
    "float3 rgb = showShift ? shift : encode_log(outl, ws);", "return make_float4(rgb.x, rgb.y, rgb.z, alphaOut);"])

t_tr = norm(func_body(TEXT, "transform") or "")
t_rh = norm(func_body(TEXT, "remap_hue") or "")
sites = re.findall(r"float sigma = [^;]+;", t_rh) + re.findall(r"float sigma = [^;]+;", t_tr)
check(len(sites) == 2 and sites[0] == sites[1] == SIGMA,
      f"{NAME}: the width blend sigma is the same statement in remap_hue() and transform() (one shared kernel)")


def dctl_sigma(stmt):
    """numpy function (d, s) -> sigma from a DCTL `float sigma = (cond) ? A : B;` statement (whitelisted tokens only)"""
    m = re.fullmatch(r"float sigma = \((.+?)\) \? (.+) : (.+);", stmt)
    if not m:
        return None
    parts = []
    for e in m.groups():
        if not set(re.findall(r"[A-Za-z_]\w*", re.sub(r"\d+\.\d*f?", "", e))) <= {"s", "d", "_sinf", "_cosf", "_tanhf"} \
                or re.search(r"[^\w\s.+\-*/()<>=]", e):
            return None
        e = re.sub(r"(\d+\.\d*)f\b", r"\1", e)
        parts.append(e.replace("_sinf", "np.sin").replace("_cosf", "np.cos").replace("_tanhf", "np.tanh"))
    cond, a, b = parts
    return lambda d, s: eval(a, {"np": np}, {"d": d, "s": s}) if eval(cond, {}, {"s": s}) \
        else eval(b, {"np": np}, {"d": d, "s": s})


SIGFN = [dctl_sigma(st) for st in sites]
xd1 = np.linspace(-np.pi, np.pi, 20_001)
e1 = max((np.abs(fin(f(xd1, s), "DCTL sigma") - sm.width_sigma(xd1, s)).max() if f else np.inf) for f in SIGFN for s in (0.0, 0.16, 4.0, 16.0)) \
    if SIGFN else np.inf
check(len(SIGFN) == 2 and e1 < 1e-15, f"{NAME}: the sigma statement of each site, evaluated from the DCTL text, == "
                                      f"skinmodel.width_sigma (max |diff| {e1:.1e}, s in {{0, 0.16, 4, 16}})")
CMP_RX = r"\(\s*[\w.]+\s*(?:[<>]=?|==|!=)\s*[\w.+-]+\s*\)"
cmp_tr, cmp_rh = re.findall(CMP_RX, t_tr), re.findall(CMP_RX, t_rh)
CMP_WANT = ["(C > 0.0f)", "(delta > 1e-4f)", "(k2 > 0.0f)", "(m8 > 0.0f)", "(s > 0.0f)"]
check(sorted(cmp_tr) == CMP_WANT and cmp_rh == ["(s > 0.0f)"]
      and not re.search(r"[^\w](?:d|h|C)\s*[<>]", t_tr.replace("(C > 0.0f)", "") + t_rh),
      f"{NAME}: the only comparisons are the C > 0 atan2 guard (numerical: at C = 0 the output does not depend on h), "
      f"the UI-parameter guards k2 / m8 / s and the tolerance guard; none on the hue distance d (found {cmp_tr} + {cmp_rh})")
mm = sorted(calls_of(t_tr, "_fmaxf") + calls_of(t_tr, "_fminf") + calls_of(t_tr, "_clampf"))
MM_WANT = sorted([
    "_fmaxf(C, 1e-12f)",                                                  # floor inside the log (not a branch)
    "_fminf(hueStrength * wField, 0.99f)", "_fminf(chromaStrength * wField * kH, 0.99f)",   # 0.99 strength clamps
    "_clampf(u / delta, -20.0f, 20.0f)",                                  # fast-math guard, no-op (tanh(20) == 1 in float32)
    "_fmaxf(zoneLumaMax, 0.01f)", "_fmaxf(lipsChromaMin, 0.001f)",        # UI-parameter clamps
    "_fminf(_fmaxf(zoneHueYellow, 1.0f), 180.0f)", "_fmaxf(zoneHueYellow, 1.0f)",
    "_fminf(_fmaxf(zoneHueRed, 1.0f), 180.0f)", "_fmaxf(zoneHueRed, 1.0f)"])
check(mm == MM_WANT and not calls_of(t_rh, "_fmaxf") + calls_of(t_rh, "_fminf") + calls_of(t_rh, "_clampf"),
      f"{NAME}: min/max/clamp in transform() are only the log floor, the two 0.99 strength clamps, the tanh-argument "
      f"guard and UI-parameter clamps; none on the red width or another pixel quantity, none in remap_hue() ({len(mm)} found)"
      + ("" if mm == MM_WANT else f"\n     got:  {mm}\n     want: {MM_WANT}"))
check("0.6f" not in t_tr and t_tr.count("tiltPivot") == 2 and 0 <= t_tr.find("float Lc ") < t_tr.find("float u "),
      f"{NAME}: no 0.6f pivot literal in transform(), tiltPivot used by both tilts, Lc computed before the chroma tilt")
check(not re.search(r"\bshowZone\b|\bwidth\b", code), f"{NAME}: no retired showZone / width identifier in the code")
check(np.float32(100.0) * np.float32(0.01) == np.float32(1.0),
      "sanity (float32 arithmetic fact, not a gate on the DCTL): float32(100) * 0.01f == 1.0f exactly, so at Chroma "
      "Lift 100 lift == 1 and g == th bit for bit")
check(np.tanh(np.float32(20.0)) == np.float32(1.0) and np.tanh(np.float32(-20.0)) == np.float32(-1.0),
      "sanity (float32 arithmetic fact, not a gate on the DCTL): tanh(+-20) == +-1 exactly in float32, so the +-20 "
      "clamp on u/delta cannot change the result")

# model entry points: parsed defaults and model() == pixel()
UI = sm.parse_ui_defaults(TEXT)
check(list(UI) == list(sm.PARAMS) and UI["outputAlpha"] == 1 and UI["showShift"] == 0,
      f"{NAME}: parse_ui_defaults() keys == skinmodel.PARAMS in order ({len(UI)}), Output Zone Alpha on, Show Shift off")
P0 = {**UI, "showShift": 0}                    # default parameter set of the model
x14 = np.random.default_rng(14).uniform(-0.05, 1.2, (1000, 3))
o14m, a14m = sm.model(x14, TEXT, fname=NAME)
o14p, a14p, _ = sm.pixel(x14, P0, cct_dec, cct_enc, to_lab, from_lab)
check(np.array_equal(o14m, o14p) and np.array_equal(a14m, a14p),
      f"{NAME}: skinmodel.model() == pixel(..., defaults) bit-for-bit on 1000 codes (RGB and alpha)")

# The model's constants are the DCTL literals.
lit = lambda rx: float(m.group(1)) if (m := re.search(rx, t_tr)) else np.nan   # noqa: E731
CONSTS = {"LIFT_EPS": (sm.LIFT_EPS, lit(r"float xl = _fabs\(th\) / (\d+\.\d*)f;")),
          "EDGE_GAIN": (sm.EDGE_GAIN, lit(r"float s = (\d+\.\d*)f \* zoneHueEdge;")),
          "LIPS_FLOOR": (sm.LIPS_FLOOR, lit(r"\(1\.0f - (\d+\.\d*)f \* lipsProtect \* cL\)"))}
check(all(a == b for a, b in CONSTS.values()), f"skinmodel constants == DCTL literals: "
      + ", ".join(f"{k} {a} vs {b}" for k, (a, b) in CONSTS.items()))

# Independent per-statement formula: the DCTL's own transform() / remap_hue() / softplus() statements,
# transpiled to numpy (float64), against skinmodel.pixel_core() on Oklab input, over random parameter
# draws across the full UI ranges. Any literal or operation the model copies differently shows up here.
FN_NP = {"_fminf": "np.minimum", "_fmaxf": "np.maximum", "_expf": "np.exp", "_logf": "np.log", "_tanhf": "np.tanh",
         "_sinf": "np.sin", "_cosf": "np.cos", "_sqrtf": "np.sqrt", "_atan2f": "np.arctan2", "_round": "np.round",
         "_fabs": "np.abs", "_clampf": "np.clip"}
NOT_SCALAR = re.compile(r"\bfloat3\b|make_float|encode_log|decode_log|oklab_to_rgb|rgb_to_oklab|\blabn\b|\bws\b")


def py_expr(e):
    e = re.sub(r"(?<![\w.])(\d+(?:\.\d*)?(?:e[+-]?\d+)?)f\b", r"\1", e)       # 1.0f -> 1.0, 1e-4f -> 1e-4
    for k, v in FN_NP.items():
        e = re.sub(r"\b" + k + r"\(", v + "(", e)
    return e


def py_stmt(st):
    """one normalised scalar DCTL statement (`[float|int] x = e;`, `x = e;`, `return e;`) -> python"""
    st = st.strip().rstrip(";")
    if st.startswith("return "):
        return "_ret = " + py_expr(st[7:])
    m = re.fullmatch(r"(?:float |int )?(\w+) = (.+)", st)
    if not m:
        raise ValueError(f"cannot transpile: {st}")
    name, rhs = m.groups()
    if " ? " in rhs:
        cond, rest_ = rhs.split(" ? ", 1)
        a, b = rest_.rsplit(" : ", 1)
        return f"{name} = np.where({py_expr(cond)}, {py_expr(a)}, {py_expr(b)})"
    return f"{name} = {py_expr(rhs)}"


def py_func(fn, params, skip=None):
    """(statements, runner) for a DCTL function body; runner(ns) executes them in namespace ns"""
    stmts = [s for s in re.split(r"(?<=;) ", norm(func_body(TEXT, fn) or "")) if s and not (skip and skip.search(s))]
    code_ = compile("\n".join(py_stmt(s) for s in stmts), f"<{fn}>", "exec")
    return lambda ns: exec(code_, ns) or ns


try:
    run_sp = py_func("softplus", ("x", "k"))
    run_rh = py_func("remap_hue", ("h", "target", "wY", "wR", "s", "str"))
    run_tr = py_func("transform", (), NOT_SCALAR)

    def dctl_softplus(x, k):
        return run_sp({"np": np, "x": x, "k": k})["_ret"]

    def dctl_remap_hue(h, target, wY, wR, s, str_):
        return run_rh({"np": np, "h": h, "target": target, "wY": wY, "wR": wR, "s": s, "str": str_})["_ret"]

    rng1 = np.random.default_rng(101)
    UI_RANGE = {m.group(1): (float(m.group(2)), float(m.group(3))) for m in re.finditer(
        r"DEFINE_UI_PARAMS\((\w+), [^,]+, DCTLUI_SLIDER_FLOAT, [-\d.]+, ([-\d.]+), ([-\d.]+), [\d.]+\)", "\n".join(ui_want))}
    worst1, n1, at1 = 0.0, 0, None
    for draw in range(300):
        p = {k: float(rng1.uniform(lo, hi)) for k, (lo, hi) in UI_RANGE.items()}
        p.update(zoneLumaWindow=int(draw % 2 == 0), outputAlpha=int(rng1.integers(0, 2)), showShift=0, workingSpace=0)
        if draw % 3 == 0:                          # a third of the draws on the default parameters' edges of interest
            p.update(chromaLift=float(rng1.uniform(0, 99)), lipsProtect=float(rng1.uniform(0.2, 1)),
                     zoneHueEdge=float(rng1.uniform(0.01, 0.99)), mix=float(rng1.uniform(0, 0.99)))
        L = rng1.uniform(-0.2, 1.5, 2000)
        Cc = np.concatenate([[0.0], rng1.uniform(0, 0.5, 1999)])
        hh = rng1.uniform(-np.pi, np.pi, 2000)
        lab1 = np.stack([L, Cc * np.cos(hh), Cc * np.sin(hh)], axis=1)
        pA = rng1.uniform(0, 1, 2000)
        with np.errstate(divide="ignore", invalid="ignore"):   # np.where evaluates both ternary branches
            ns = run_tr({"np": np, **p, "lab": type("v", (), dict(x=lab1[:, 0], y=lab1[:, 1], z=lab1[:, 2])),
                         "p_A": pA, "softplus": dctl_softplus, "remap_hue": dctl_remap_hue})
        out, al, inf = sm.pixel(lab1, {**p, "showShift": 1}, ident, ident, ident, ident, pA)
        ex = inf["ex"]
        Cn_d = ns["Cn"]
        labn_d = lab1 + (np.stack([lab1[:, 0], Cn_d * np.cos(ns["hn"]), Cn_d * np.sin(ns["hn"])], axis=1) - lab1) * p["mix"]
        diffs = [np.abs(ex["hn"] - ns["hn"]), np.abs(ex["wC"] - ns["wC"]), np.abs(ex["g"] - ns["g"]),
                 np.abs(inf["a"] - ns["a"]), np.abs(al - ns["alphaOut"]), np.abs(ex["kH"] - ns["kH"]),
                 np.abs(inf["labn"] - labn_d).max(axis=1),
                 np.abs(out[:, 0] - (0.5 + ns["dh"] * 57.29577951 / 60.0 * p["mix"])),
                 np.abs(out[:, 1] - (0.5 + ns["dlnC"] * p["mix"]))]
        d1 = max(fin(dd, "model vs transpiled DCTL").max() for dd in diffs)
        n1 += 1
        if not d1 <= worst1:
            worst1, at1 = d1, {k: round(v, 4) for k, v in p.items()}
    check(worst1 < 1e-8, f"skinmodel.pixel_core() == the DCTL transform() statements transpiled to numpy (hn, wC, g, kH, "
                         f"zone alpha, alpha out, labn after Mix, Show Shift R / G) on {n1} random draws of every slider over "
                         f"its UI range (window on/off, a third with Lift < 100, Lips on, Edge in (0, 1), Mix < 1) x 2000 "
                         f"random Oklab points: max |diff| {worst1:.1e} < 1e-8" + ("" if worst1 < 1e-8 else f" at {at1}"))
except Exception as exc:                       # noqa: BLE001  (a mutated body must FAIL, not crash)
    check(False, f"{NAME}: transform() / remap_hue() / softplus() could not be transpiled and compared: {exc!r}")

# =====================================================================
# 2. Matrices
# =====================================================================
GEN = gm.dctl_blocks()
check(all(b in TEXT for b in GEN), f"{NAME}: both blocks printed by tools/gen_matrices.py (per-space and Oklab matrix "
                                   f"functions, {sum(b.count(chr(10)) + 1 for b in GEN)} lines) appear verbatim in the DCTL")
for _, enum, prim, white in gm.SPACES:
    Md = gm.rgb_to_xyz_d65(prim, white)
    fwd, inv = MATS[f"{enum}_TO_XYZ"], MATS[f"XYZ_TO_{enum}"]
    e_1, e_2 = np.abs(fwd - Md).max(), np.abs(inv - np.linalg.inv(Md)).max()
    e_3 = max(np.abs(inv @ fwd - np.eye(3)).max(), np.abs(fwd @ inv - np.eye(3)).max())
    check(e_1 < 1e-9 and e_2 < 1e-9, f"{enum}_TO_XYZ / XYZ_TO_{enum} match derivation (max err {e_1:.1e} / {e_2:.1e})")
    check(e_3 < 2e-8, f"XYZ_TO_{enum} inverts {enum}_TO_XYZ (max |P - I| {e_3:.1e})")
    det = np.linalg.det(fwd)
    check(det > 0, f"det({enum}_TO_XYZ) = {det:.6f} > 0")
check(np.array_equal(MATS["OKLAB_M1"], gm.M1), "OKLAB_M1 equals Ottosson's published M1 exactly")
check(np.array_equal(MATS["OKLAB_M2"], gm.M2), "OKLAB_M2 equals Ottosson's published M2 exactly")
check(np.array_equal(MATS["OKLAB_M2_INV"], gm.M2_INV_PUBLISHED), "OKLAB_M2_INV equals the published inverse exactly")
e_m1i = np.abs(MATS["OKLAB_M1_INV"] - np.linalg.inv(gm.M1)).max()
e_m1p = np.abs(MATS["OKLAB_M1_INV"] @ MATS["OKLAB_M1"] - np.eye(3)).max()
e_m2p = np.abs(MATS["OKLAB_M2_INV"] @ MATS["OKLAB_M2"] - np.eye(3)).max()
check(e_m1i < 1e-9 and e_m1p < 2e-8, f"OKLAB_M1_INV = inv(M1) (err {e_m1i:.1e}), M1_INV*M1 = I ({e_m1p:.1e})")
# The published M2^-1 is not the float64 inverse of M2: it is good to ~1 float32 ulp at 1.0
# (2^-24 = 6.0e-8), not to 2e-8; see section 3.
check(e_m2p < 1e-7, f"OKLAB_M2_INV*M2 = I to {e_m2p:.1e} < 1e-7 (published coefficients; float32 eps 6.0e-8)")

# Independent of gen_matrices.py: the PUBLISHED ACES AP1 -> XYZ (ACES white) matrix, Bradford ACES white -> D65
# (written out here), then Ottosson's M1 and M2. A wrong CAT or AP1 primary shows up here and in section 5.
AP1_XYZ = np.array([[0.6624541811, 0.1340042065, 0.1561876870],
                    [0.2722287168, 0.6740817658, 0.0536895174],
                    [-0.0055746495, 0.0040607335, 1.0103391003]])
BRADFORD = np.array([[0.8951, 0.2664, -0.1614],
                     [-0.7502, 1.7135, 0.0367],
                     [0.0389, -0.0685, 1.0296]])
M1 = np.array([[0.8189330101, 0.3618667424, -0.1288597137],
               [0.0329845436, 0.9293118715, 0.0361456387],
               [0.0482003018, 0.2643662691, 0.6338517070]])
M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
               [1.9779984951, -2.4285922050, 0.4505937099],
               [0.0259040371, 0.7827717662, -0.8086757660]])


def xy2XYZ(x, y):
    return np.array([x / y, 1.0, (1 - x - y) / y])


w_src, w_dst = xy2XYZ(0.32168, 0.33767), xy2XYZ(0.3127, 0.3290)  # ACES white -> D65
CAT = np.linalg.inv(BRADFORD) @ np.diag((BRADFORD @ w_dst) / (BRADFORD @ w_src)) @ BRADFORD
A = M1 @ CAT @ AP1_XYZ          # AP1 linear -> LMS
Ai = np.linalg.inv(A)
M2i = np.linalg.inv(M2)


def oklab_ref(rgb):
    return (M2 @ np.cbrt(A @ rgb.T)).T


def ap1_ref(lab):
    return (Ai @ ((M2i @ lab.T) ** 3)).T


e_fold = np.abs(MATS["OKLAB_M1"] @ MATS["AP1_TO_XYZ"] - A).max()
check(e_fold < 1e-8, f"M1 * AP1_TO_XYZ == M1 * Bradford * published ACES AP1->XYZ (independent derivation, max err {e_fold:.1e})")
e_dwg = np.abs(MATS["DWG_TO_XYZ"] - gm.OFFICIAL["DWG"]).max()
e_awg = np.abs(MATS["AWG4_TO_XYZ"] - gm.OFFICIAL["AWG4"]).max()
e_709 = np.abs(MATS["REC709_TO_XYZ"] - gm.OFFICIAL["REC709"]).max()
check(e_dwg < 6e-9, f"DWG_TO_XYZ equals the BMD whitepaper matrix (max err {e_dwg:.1e})")
check(e_awg < 1e-9, f"AWG4_TO_XYZ equals the ARRI LogC4 spec matrix (max err {e_awg:.1e})")
check(e_709 < 1e-4, f"REC709_TO_XYZ equals the IEC 61966-2-1 / BT.709 published matrix to {e_709:.1e} < 1e-4 (printed to 4 digits)")
# Oklab of the D65 white is not exactly (1, 0, 0) with Ottosson's published M1 and D65 xy (0.3127, 0.3290):
# L 0.9999988, C 1.25e-4 for ANY D65-white input. So each white is compared with the Oklab of the exact xy
# D65 white and with the other spaces' white.
w_709 = to_lab(np.ones((1, 3)), "REC709")[0]
wd65 = gm.M2 @ np.cbrt(gm.M1 @ gm.xy2XYZ(*gm.D65))
wsp = max(np.abs(fin(to_lab(np.ones((1, 3)), m)[0], "white") - w_709).max() for m in ("AP1", "DWG", "AWG4"))
check(np.abs(w_709 - wd65).max() < 1e-9 and wsp < 1e-6,
      f"Oklab of Rec.709 linear (1, 1, 1) == Oklab of xy D65 (max |diff| {np.abs(w_709 - wd65).max():.1e}) and of the "
      f"AP1 / DWG / AWG4 white (max {wsp:.1e}): L = {w_709[0]:.9f}, C = {np.hypot(w_709[1], w_709[2]):.2e} (inherent to the "
      f"published M1 at D65, not 1 / 0)")

# =====================================================================
# 3. Oklab round trips
# =====================================================================
rng = np.random.default_rng(0)
x3 = rng.uniform(0, 2, (100_000, 3))
err = np.abs(ap1_ref(oklab_ref(x3)) - x3).max()
check(err < 1e-10, f"Oklab round-trip (derived matrices) max err {err:.2e}")

# Ottosson's PUBLISHED M2^-1 (kept verbatim) is accurate to 6.2e-8 only (true inverse column 0 is
# 1.00000001 / 1.00000005, published 1.0): about one float32 ulp at 1.0, invisible in the DCTL's float32
# but dominant in a float64 plain round trip. Both are measured:
#   (a) DCTL matrices with M2^-1 = inv(OKLAB_M2): every matrix and curve, < 1e-6 encoded and linear;
#   (b) DCTL matrices verbatim: linear (rel+abs) < 1e-6; the encoded error is printed (the 6e-8 linear
#       error seen through the log toe slope near 0). The output form lin + (F(labn) - F(lab)) cancels it.
rng3 = np.random.default_rng(10)
lin3 = np.vstack([rng3.uniform(0, 2, (100_000, 3)), rng3.uniform(1e-5, 1e-3, (20_000, 3))])
M2_INV_EXACT = np.linalg.inv(MATS["OKLAB_M2"])
for ws in WS_ORDER:
    enc, dec, _ = CURVES[ws]
    mat = WS_MAT[ws]
    x_enc = enc(lin3)
    lab3 = to_lab(dec(x_enc), mat)
    for tg, m2i in (("(a) exact M2^-1", M2_INV_EXACT), ("(b) published M2^-1", None)):
        back = from_lab(lab3, mat, m2i)
        e_enc = np.abs(enc(back) - x_enc).max()
        e_lin = (np.abs(back - lin3) / (np.abs(lin3) + 1.0)).max()
        if m2i is not None:
            check(e_enc < 1e-6 and e_lin < 1e-6,
                  f"{ws}: full round trip {tg}: max err encoded {e_enc:.1e}, linear (rel+abs) {e_lin:.1e}")
        else:
            check(e_lin < 1e-6, f"{ws}: full round trip {tg}: linear (rel+abs) {e_lin:.1e} < 1e-6 (encoded {e_enc:.1e}, see note)")

# Output form: outl = lin + (F(labn) - F(lab)), F = DCTL Oklab -> AP1. At Mix 0 labn == lab so
# outl == lin bit-exactly; otherwise the round-trip bias of the published constants cancels.
# Dummy edit: rotate (a, b) by 10 deg.
lab_d = to_lab(x3)
err_d = np.abs(from_lab(lab_d) - x3).max()
th3 = np.radians(10.0)
ROT = np.array([[1, 0, 0], [0, np.cos(th3), -np.sin(th3)], [0, np.sin(th3), np.cos(th3)]])
labn_d = lab_d @ ROT.T
err_out = np.abs(x3 + (from_lab(labn_d) - from_lab(lab_d)) - ap1_ref(labn_d)).max()
err_plain = np.abs(from_lab(labn_d) - ap1_ref(labn_d)).max()
check(err_out < err_d, f"output form lin + (F(labn) - F(lab)) error vs exact inverse {err_out:.2e} < round-trip error "
                       f"{err_d:.2e} (plain F(labn): {err_plain:.2e})")
del x3, lab_d, labn_d, lin3, lab3, back

# =====================================================================
# 4. Working-space curves (closed forms from the official specs, in skinmodel.py)
# =====================================================================


def lin_grid(lo, hi, n=200_001):
    """Dense grid over [lo, hi]: linear near zero plus log-spaced positives."""
    pos = np.logspace(np.log10(max(lo, 1e-12)), np.log10(hi), n)
    neg = np.linspace(lo, 0, n // 4) if lo < 0 else np.array([])
    near = np.linspace(max(lo, 0.0), min(hi, 0.01), n // 4)
    g = np.unique(np.concatenate([neg, near, pos]))
    return g[(g >= lo) & (g <= hi) & ((g > 0) if lo > 0 else True)]


LOG_SPACES = ("ACEScct", "ACEScc", "DWG", "LogC4")
for name in LOG_SPACES:
    enc, dec, (lo, hi) = CURVES[name]
    L = lin_grid(lo, hi)
    E = enc(L)
    rt = np.abs(dec(E) - L) / np.maximum(np.abs(L), 1e-3)
    check(rt.max() < 1e-12, f"{name}: decode(encode(lin)) == lin on [{lo:.4g}, {hi:.4g}], "
                            f"max rel err {rt.max():.1e} (abs below |lin| 1e-3)")
    X = np.linspace(E.min(), E.max(), 400_001)
    xr = np.abs(enc(dec(X)) - X).max()
    check(xr < 1e-12, f"{name}: encode(decode(x)) == x on [{E.min():.6f}, {E.max():.6f}], max err {xr:.1e}")
    check(np.all(np.diff(E) > 0), f"{name}: encode strictly increasing on its linear domain")
    L = lin_grid(lo, hi, 100_001)
    hstep = 1e-7 * np.maximum(np.abs(L), 1e-3)
    der = (enc(L + hstep) - enc(L - hstep)) / (2 * hstep)
    check(np.all(der > 0), f"{name}: encode derivative > 0 on [{lo:.4g}, {hi:.4g}] (min {der.min():.3e})")

bp = {   # breakpoints: both branches agree
    "ACEScct enc @ 2^-7": (10.5402377416545 * 0.0078125 + 0.0729055341958355, (np.log2(0.0078125) + 9.72) / 17.52, 1e-9),
    "ACEScct dec @ 0.155251141552511": (2.0 ** (0.155251141552511 * 17.52 - 9.72),
                                        (0.155251141552511 - 0.0729055341958355) / 10.5402377416545, 1e-9),
    "ACEScc enc @ 2^-15": ((np.log2(TWO_M16 + TWO_M15 * 0.5) + 9.72) / 17.52, (np.log2(TWO_M15) + 9.72) / 17.52, 1e-9),
    "ACEScc dec @ (9.72-15)/17.52": ((2.0 ** (CC_LOWCUT * 17.52 - 9.72) - TWO_M16) * 2, 2.0 ** (CC_LOWCUT * 17.52 - 9.72), 1e-9),
    "ACEScc dec @ (log2(65504)+9.72)/17.52": (2.0 ** (CC_HICUT * 17.52 - 9.72), 65504.0, 1e-9 * 65504),
    "DI enc @ DI_LIN_CUT": ((np.log2(DI_LIN_CUT + DI_A) + DI_B) * DI_C, DI_LIN_CUT * DI_M, 1e-9),
    "DI dec @ DI_LOG_CUT": (2.0 ** (DI_LOG_CUT / DI_C - DI_B) - DI_A, DI_LOG_CUT / DI_M, 1e-9),
    "LogC4 enc @ t": ((np.log2(LC4_A * LC4_T + 64) - 6) / 14 * LC4_B + LC4_C, 0.0, 1e-9),
    "LogC4 dec @ 0": ((2.0 ** (14 * (0 - LC4_C) / LC4_B + 6) - 64) / LC4_A, LC4_T, 1e-9),
}
for k, (a_, b_, tol) in bp.items():
    check(abs(a_ - b_) < tol, f"breakpoint {k}: branches agree, |diff| {abs(a_ - b_):.1e}")

refs = [
    ("ACEScct(0.18)", float(cct_enc(np.array(0.18))), 0.413588402, 1e-9),
    ("ACEScc(0.18)", float(cc_enc(np.array(0.18))), float(cct_enc(np.array(0.18))), 1e-12),
    ("DI(0.18)", float(di_enc(np.array(0.18))), 0.336043, 5e-7),
    ("DI(1.0)", float(di_enc(np.array(1.0))), 0.513837, 5e-7),
    ("DI(100)", float(di_enc(np.array(100.0))), 1.0, 5e-7),
    ("LogC4(0)", float(lc4_enc(np.array(0.0))), 0.0929, 5e-5),
    ("LogC4(0.18)", float(lc4_enc(np.array(0.18))), 0.2784, 5e-5),
    ("Rec709 enc(0.18)", float(sm.r709_enc(np.array(0.18))), 0.18 ** (1 / 2.4), 1e-15),
    ("Rec709 dec(0.5)", float(sm.r709_dec(np.array(0.5))), 0.5 ** 2.4, 1e-15),
    ("sRGB enc(0.18)", float(sm.srgb_enc(np.array(0.18))), 0.4614, 5e-5),   # 0.461356 (4 digits: 0.4614)
    ("sRGB dec(0.5)", float(sm.srgb_dec(np.array(0.5))), 0.2140, 5e-5),
]
for k, got, want, tol in refs:
    check(abs(got - want) < tol, f"reference {k} = {got:.9f} (expected {want:.9g})")

# Rec.709 Gamma 2.4 and sRGB. The IEC sRGB constants are not exactly continuous: the encode steps back
# by 2.85e-8 (code) at lin 0.0031308 and the decode steps up by 2.3e-9 (linear) at code 0.04045. Inside
# the band lin in [0.0031308, 0.0031308073] (7.3e-9 wide) encode lands below the decode cut, so the
# round trip there is off by up to 2.3e-6 relative. Grid points sit exactly on both cuts.
CUT_E, CUT_D, BAND = 0.0031308, 0.04045, (0.0031308, 0.0031308073)
for name in ("Rec709", "sRGB"):
    enc, dec, (lo, hi) = CURVES[name]
    up = np.nextafter(CUT_E, 1.0)                  # first lin above the cut: the upper branch
    cuts_L = [-up, -CUT_E, CUT_E, up, BAND[1]] if name == "sRGB" else []
    L = np.unique(np.concatenate([lin_grid(lo, hi), cuts_L]))
    E = enc(L)
    X = np.unique(np.concatenate([np.linspace(E.min(), E.max(), 400_001), [-CUT_D, CUT_D] if name == "sRGB" else []]))
    out = (np.abs(L) < BAND[0]) | (np.abs(L) > BAND[1]) if name == "sRGB" else np.ones_like(L, dtype=bool)
    rt = (np.abs(dec(E) - L) / np.maximum(np.abs(L), 1e-3))[out]
    xr = np.abs(enc(dec(X)) - X) / np.maximum(np.abs(X), 1e-3)
    if name == "sRGB":
        xr = xr[np.abs(np.abs(X) - CUT_D) > 1e-7]
    check(rt.max() < 1e-12 and xr.max() < 1e-12,
          f"{name}: decode(encode(lin)) == lin on [{lo:g}, {hi:g}] (max rel err {rt.max():.1e}, abs below 1e-3) and "
          f"encode(decode(x)) == x on [{E.min():.4f}, {E.max():.4f}] (max {xr.max():.1e})"
          + (" outside the IEC band lin in [0.0031308, 0.0031308073] / code within 1e-7 of 0.04045" if name == "sRGB" else ""))
    dE, dD = np.diff(E), np.diff(dec(X))
    if name == "Rec709":
        check(np.all(dE > 0) and np.all(dD > 0), f"{name}: encode and decode strictly increasing")
    else:
        stepE = dE[dE <= 0]
        check(np.all(dD > 0) and len(stepE) == 2 and np.all(np.abs(stepE + 2.85e-8) < 1e-9),
              f"{name}: decode strictly increasing (steps up {((CUT_D + 0.055) / 1.055) ** 2.4 - CUT_D / 12.92:.1e} at 0.04045); "
              f"encode non-decreasing except the IEC step at the cut (measured "
              f"{(stepE.min() if len(stepE) else np.nan):.2e} at lin +-0.0031308, {len(stepE)} steps)")
    check(np.array_equal(enc(-L), -enc(L)) and np.array_equal(dec(-X), -dec(X)), f"{name}: encode and decode odd (mirrored about 0, exact)")
bd = abs(0.04045 / 12.92 - ((0.04045 + 0.055) / 1.055) ** 2.4)
be = abs(12.92 * 0.0031308 - (1.055 * 0.0031308 ** (1 / 2.4) - 0.055))
check(bd < 1e-6 and be < 1e-6, f"sRGB breakpoints: decode branches at 0.04045 differ by {bd:.1e} (linear, upper above), "
                               f"encode branches at 0.0031308 by {be:.1e} (code, upper below: a step back): < 1e-6, the "
                               f"mismatch inherent to the IEC constants")

# every #define of the DCTL, with its sign (parentheses allowed), vs the specs
DI_STR = {"DI_A": "0.0075", "DI_B": "7.0", "DI_C": "0.07329248", "DI_M": "10.44426855",
          "DI_LIN_CUT": "0.00262409", "DI_LOG_CUT": "0.02740668"}
LC4_VAL = {"LC4_A": LC4_A, "LC4_B": LC4_B, "LC4_C": LC4_C, "LC4_S": LC4_S, "LC4_T": LC4_T}
DEFINES = {m.group(1): m.group(2) for m in re.finditer(
    r"^[ \t]*#define[ \t]+(\w+)[ \t]+\(?[ \t]*([+-]?\d+\.\d+)f[ \t]*\)?[ \t]*(?://[^\n]*)?$", TEXT, re.M)}
all_defines = re.findall(r"^[ \t]*#define[ \t]+(\w+)", TEXT, re.M)
check(sorted(all_defines) == sorted(DEFINES) == sorted(list(DI_STR) + list(LC4_VAL)),
      f"{NAME}: #defines are exactly the DI and LogC4 constants, all parsed ({sorted(all_defines)})")
for k, v in DI_STR.items():
    check(DEFINES.get(k) == v, f"{NAME}: #define {k} {DEFINES.get(k)} == BMD whitepaper {v}")
for k, v in LC4_VAL.items():
    got = float(DEFINES[k]) if k in DEFINES else np.nan
    check(abs(got - v) <= 1e-12 * abs(v), f"{NAME}: #define {k} {DEFINES.get(k)} == closed form {v!r} (1e-12 rel)")

# the 12 curve functions, exact bodies: the closed forms of the specs quoted in the DCTL
CURVE_BODIES = {
    "cct_to_lin": "return (x > 0.155251141552511f) ? _exp2f(x * 17.52f - 9.72f) : (x - 0.0729055341958355f) / 10.5402377416545f;",
    "lin_to_cct": "return (x <= 0.0078125f) ? 10.5402377416545f * x + 0.0729055341958355f : (_log2f(x) + 9.72f) / 17.52f;",
    "cc_to_lin": "if (x <= -0.3013698630136986f) return (_exp2f(x * 17.52f - 9.72f) - 0.0000152587890625f) * 2.0f; if (x < 1.4679963120447153f) return _exp2f(x * 17.52f - 9.72f); return 65504.0f;",
    "lin_to_cc": "if (x <= 0.0f) return -0.3584474885844748f; if (x < 0.000030517578125f) return (_log2f(0.0000152587890625f + x * 0.5f) + 9.72f) / 17.52f; return (_log2f(x) + 9.72f) / 17.52f;",
    "di_to_lin": "return (x > DI_LOG_CUT) ? _exp2f(x / DI_C - DI_B) - DI_A : x / DI_M;",
    "lin_to_di": "return (x > DI_LIN_CUT) ? (_log2f(x + DI_A) + DI_B) * DI_C : x * DI_M;",
    "logc4_to_lin": "return (x >= 0.0f) ? (_exp2f(14.0f * (x - LC4_C) / LC4_B + 6.0f) - 64.0f) / LC4_A : x * LC4_S + LC4_T;",
    "lin_to_logc4": "return (x >= LC4_T) ? (_log2f(LC4_A * x + 64.0f) - 6.0f) / 14.0f * LC4_B + LC4_C : (x - LC4_T) / LC4_S;",
    "r709_to_lin": "return _copysignf(_powf(_fabs(x), 2.4f), x);",
    "lin_to_r709": "return _copysignf(_powf(_fabs(x), 1.0f / 2.4f), x);",
    "srgb_to_lin": "return (_fabs(x) <= 0.04045f) ? x / 12.92f : _copysignf(_powf((_fabs(x) + 0.055f) / 1.055f, 2.4f), x);",
    "lin_to_srgb": "return (_fabs(x) <= 0.0031308f) ? 12.92f * x : _copysignf(1.055f * _powf(_fabs(x), 1.0f / 2.4f) - 0.055f, x);",
}
check(abs(-0.3013698630136986 - CC_LOWCUT) < 1e-15 and abs(1.4679963120447153 - CC_HICUT) < 1e-15
      and abs(-0.3584474885844748 - CC_FLOOR) < 1e-15 and 0.0000152587890625 == TWO_M16
      and 0.000030517578125 == TWO_M15, "ACEScc inline literals equal (9.72-15)/17.52, (log2 65504+9.72)/17.52, floor, 2^-16, 2^-15")
for fn, want in CURVE_BODIES.items():
    m = re.search(r"__DEVICE__ float " + fn + r"\(float x\) \{", TEXT)
    got = norm(func_body(TEXT, fn) or "") if m else None
    check(got == want, f"{NAME}: {fn}() body is the canonical closed form"
                       + ("" if got == want else f"\n     got:  {got}\n     want: {want}"))

# =====================================================================
# 5. ColorChecker dark / light skin through all six spaces
# =====================================================================
# Reference: the patch through the independent derivation of section 2 (AP0 -> AP1 -> published AP1 -> XYZ,
# Bradford, Ottosson): h 42.9491 / 44.5029 deg. The per-space loop alone cannot fail (codes built with
# XYZ_TO_ws, read back with ws_TO_XYZ); the comparison with the reference is what catches a wrong CAT.
# Measured once by hand: no CAT gives h 45.523 / 47.984 deg (C 0.0590 / 0.0700), CAT02 gives 42.848 /
# 44.396 deg (C 0.05476 / 0.06309): both fail at 1e-3 deg / 1e-5 C.
NPM_AP0 = gm.npm([(0.73470, 0.26530), (0.00000, 1.00000), (0.00010, -0.07700)], (0.32168, 0.33767))
CAT_ACES_D65 = gm.bradford((0.32168, 0.33767), gm.D65)
for name, ap0 in cc.items():
    lab_r = oklab_ref((AP0_AP1 @ np.array(ap0))[None])[0]
    L_r, C_r, h_r = lab_r[0], np.hypot(lab_r[1], lab_r[2]), np.degrees(np.arctan2(lab_r[2], lab_r[1]))
    print(f"ref  ColorChecker {name}: L={L_r:.3f} C={C_r:.4f} h={h_r:.1f}deg")
    xyz = CAT_ACES_D65 @ NPM_AP0 @ np.array(ap0)
    res = []
    for ws in WS_ORDER:
        enc, dec, _ = CURVES[ws]
        mat = WS_MAT[ws]
        cde = enc(MATS[f"XYZ_TO_{mat}"] @ xyz)
        lab = to_lab(dec(cde)[None], mat)[0]
        res.append((lab[0], np.hypot(lab[1], lab[2]), np.degrees(np.arctan2(lab[2], lab[1]))))
        print(f"ref  {name:10s} {ws:7s}: code {np.round(cde, 6)}  L={lab[0]:.6f} C={res[-1][1]:.6f} h={res[-1][2]:.4f}deg")
    Ls, Cs, hs = (np.array([r[i] for r in res]) for i in range(3))
    check(np.ptp(Ls) < 1e-6 and np.ptp(Cs) < 1e-6 and np.ptp(hs) < 1e-4,
          f"{name}: same Oklab L/C/h in all 6 spaces (spread L {np.ptp(Ls):.1e}, C {np.ptp(Cs):.1e}, h {np.ptp(hs):.1e}deg)")
    check(np.all((hs > 40) & (hs < 48)) and np.all((Cs > 0.05) & (Cs < 0.07)),
          f"{name}: h {hs.mean():.2f}deg in 40-48 (near the skin line), C {Cs.mean():.4f} in 0.05-0.07")
    dh, dC, dL = np.abs(hs - h_r).max(), np.abs(Cs - C_r).max(), np.abs(Ls - L_r).max()
    check(dh < 1e-3 and dC < 1e-5 and dL < 1e-5,
          f"{name}: L/C/h in every space match the independent derivation L={L_r:.6f} C={C_r:.6f} h={h_r:.4f}deg "
          f"(max |dh| {dh:.1e}deg, |dC| {dC:.1e}, |dL| {dL:.1e}); catches a wrong CAT (none: 45.5/48.0deg, CAT02: 42.85/44.40deg)")

# =====================================================================
# 6. Softplus L clamp of the tilts
# =====================================================================
# Lc = L - sp(L - 1.2) + sp(-L), sp(x) = k ln(1 + e^(x/k)), k = 0.05, in the same overflow-safe form as
# the DCTL. Slope 1 - sigmoid((L-1.2)/k) - sigmoid(-L/k) in (0, 1]: strictly increasing, bounded in
# (0, 1.2), identity inside [0, 1.2] up to k ln(1 + e^-4) < 1e-3 beyond 0.2 from either edge, k ln 2 at
# the corners. Far from [0, 1.2] the slope (~e^-36 at L = 3) and the gaps to 0 and 1.2 are below float64
# resolution of Lc itself, so they are evaluated in closed form:
#   slope = sigmoid((1.2 - L)/k) * sigmoid(L/k) * (1 - e^(-1.2/k))
#   Lc - 0   = sp(L) - sp(L - 1.2)     1.2 - Lc = sp(1.2 - L) - sp(-L)
# (from sp(x) - sp(-x) = x); sp is strictly increasing, so all three are > 0.


def clamp_L(L, k=0.05):
    return L - softplus(L - 1.2, k) + softplus(-L, k)


def sigmoid(x):
    e = np.exp(-np.abs(x))
    return np.where(x >= 0, 1.0 / (1.0 + e), e / (1.0 + e))


Lg = np.linspace(-1.0, 3.0, 400_001)
Lc6 = clamp_L(Lg)
kL = 0.05
slope_L = sigmoid((1.2 - Lg) / kL) * sigmoid(Lg / kL) * -np.expm1(-1.2 / kL)
gap_lo = softplus(Lg, kL) - softplus(Lg - 1.2, kL)
gap_hi = softplus(1.2 - Lg, kL) - softplus(-Lg, kL)
inside = (Lg >= 0.2) & (Lg <= 1.0)
dev_in = np.abs(Lc6 - Lg)[inside].max()
dev_clip = np.abs(Lc6 - np.clip(Lg, 0.0, 1.2)).max()
check(slope_L.min() > 0 and np.all(np.diff(Lc6) >= 0) and slope_L.max() <= 1.0,
      f"softplus L clamp strictly increasing on L in [-1, 3]: slope in [{slope_L.min():.1e}, {slope_L.max():.6f}]")
check(gap_lo.min() > 0 and gap_hi.min() > 0 and np.allclose(gap_lo, Lc6, atol=1e-12),
      f"softplus L clamp bounded in (0, 1.2): min gap to 0 {gap_lo.min():.1e}, to 1.2 {gap_hi.min():.1e}")
check(dev_in < 1e-3 and dev_clip < 0.035,
      f"softplus L clamp |Lc - L| {dev_in:.1e} < 1e-3 on [0.2, 1.0], |Lc - clip(L)| {dev_clip:.4f} < 0.035 (k ln2)")
check(abs(clamp_L(0.6) - 0.6) < 1e-6, f"softplus L clamp Lc(0.6) = {clamp_L(0.6):.9f}")


def target_deg(L, p=UI):
    """tilted target hue (deg) of parameter set p at Oklab L"""
    return p["targetHue"] + p["targetHueTilt"] * (float(clamp_L(L)) - p["tiltPivot"])


# =====================================================================
# 7. Tilts: target bounds and the default chroma target at the skin
# =====================================================================
L7 = np.linspace(-1.0, 3.0, 40_001)
Lc7 = clamp_L(L7)
lnf7, hue7 = 0.0, 0.0
for pv in (0.2, 0.6, 1.0):
    lnf7 = max(lnf7, (1.5 * np.abs(fin(Lc7, "Lc") - pv)).max())
    hue7 = max(hue7, (60.0 * np.abs(Lc7 - pv)).max())
check(lnf7 <= 1.5 + 1e-12 and hue7 <= 60.0 + 1e-9,
      f"Tilt Pivot {{0.2, 0.6, 1.0}}, L in [-1, 3]: |k (Lc - pivot)| <= {lnf7:.12f} <= 1.5 (Ct_eff within Ct e^+-1.5), "
      f"hue target within Target Hue +- {hue7:.9f} <= 60 deg")
# With the defaults the chroma target follows L: Ct_eff = Ct exp(k (Lc - pivot)); it should land within
# 10 % of the measured chroma of the dark and light skin patches.
k7, Ct7, pv7 = UI["targetChromaTilt"] * 0.01, UI["targetChroma"], UI["tiltPivot"]
for name, ap0 in cc.items():
    lab = oklab_ref((AP0_AP1 @ np.array(ap0))[None])[0]
    L_, C_ = lab[0], np.hypot(lab[1], lab[2])
    ct_eff = Ct7 * np.exp(k7 * (float(clamp_L(L_)) - pv7))
    rel = ct_eff / C_ - 1
    check(abs(rel) < 0.10, f"defaults, {name} L={L_:.4f}: Ct_eff = {Ct7:g} * e^({k7:g} * (L - {pv7:g})) = {ct_eff:.4f} "
                           f"vs measured C {C_:.4f} ({rel * 100:+.1f} %; flat target {Ct7:g}: {(Ct7 / C_ - 1) * 100:+.1f} %)")

# =====================================================================
# 8. Hue remap: slope >= 1 - strength on the full circle
# =====================================================================
# d' = d - s sin(d) E(d), E = exp(kappa(d) (cos d - 1)), kappa = 1/w(d)^2, w(d) = wR + (wY - wR) sigma(d),
# sigma = skinmodel.width_sigma(d, 16 Edge): C-infinity and 2 pi-periodic. The constant-kappa proof
# (slope >= 1 - s) does not cover the kappa'(d) term: measured here, per side of the target.


def blend_w(d, wY, wR, s=0.0):
    return wR + (wY - wR) * sm.width_sigma(d, s)


EDGES = (0.0, 0.25, 0.5, 1.0)
W8A = (5, 10, 20, 30, 45, 60, 90, 120, 180)       # every UI-range region, Edge 0, 200 001 points
W8B = (0.5, 1, 2, 5, 45, 180)                      # down to 0.5 deg (Red 5 at the 10 % lips floor), every Edge, 400 001 points


def hue_sweep(widths, edges, n):
    i0 = n
    step = np.pi / i0
    dd = np.arange(-i0, i0 + 1) * step             # dd[i0] == 0 exactly, both ends +-pi
    neg = dd[1:] + dd[:-1] < 0                     # midpoints of the diff on the red side
    margin = {"red (d < 0)": (np.inf, None), "yellow (d > 0)": (np.inf, None)}
    smin, c0, seam = np.inf, 0.0, 0.0
    for e in edges:
        for wY_ in widths:
            for wR_ in widths:
                w = blend_w(dd, np.radians(wY_), np.radians(wR_), sm.EDGE_GAIN * e)
                E = np.exp((1.0 / (w * w)) * (np.cos(dd) - 1))       # DCTL remap_hue form
                for s in (0.0, 0.5, 0.9, 0.99):
                    sl = fin(np.diff(dd - s * np.sin(dd) * E) / step, "hue slope")
                    for side, msk in (("red (d < 0)", neg), ("yellow (d > 0)", ~neg)):
                        mm_ = sl[msk].min() - (1 - s)
                        if mm_ < margin[side][0]:
                            margin[side] = (mm_, (wY_, wR_, s, e))
                    smin = min(smin, sl.min())
                    c0 = max(c0, abs(sl[i0] - sl[i0 - 1]))          # slope(0+) vs slope(0-)
                    seam = max(seam, abs(sl[0] - sl[-1]))           # slope just after -pi vs just before +pi
    return margin, smin, c0, seam


for widths, edges, n in ((W8A, (0.0,), 100_000), (W8B, EDGES, 200_000)):
    mg, smin, c0, seam = hue_sweep(widths, edges, n)
    check(min(v[0] for v in mg.values()) > -1e-6 and c0 < 1e-4 and seam < 1e-4,
          f"hue remap slope >= 1 - strength per side on the full circle ({2 * n + 1} points), Zone Hue Range Yellow x Red in "
          f"{widths}^2 x Hue Strength {{0, 0.5, 0.9, 0.99}} x Zone Hue Edge {edges}: min slope {smin:.4f}; "
          + "; ".join(f"{k}: margin {v[0]:+.1e} at wY/wR/s/edge {v[1]}" for k, v in mg.items())
          + f"; smooth at d = 0 (|slope(0+) - slope(0-)| {c0:.1e}) and across d = +-pi ({seam:.1e}) < 1e-4")
x8 = np.linspace(-np.pi, np.pi, 100_001)
for s in (0.0, 1e-4, 1e-3, 0.16, 4.0, 16.0):
    fin(sm.width_sigma(x8, s), "sigma")
c8 = max(np.abs(sm.width_sigma(x8, s) - sm.width_sigma(x8, 0.0)).max() / s ** 2 for s in (1e-4, 1e-3))
s8 = np.abs(sm.width_sigma(x8, sm.EDGE_GAIN * 0.01) - sm.width_sigma(x8, 0.0)).max()
r8 = max(np.abs(sm.width_sigma(x8, s) - sm.width_sigma(x8 + 2 * np.pi, s)).max() for s in (0.0, 4.0, 16.0))
b8 = all(sm.width_sigma(x8, s).min() >= 0 and sm.width_sigma(x8, s).max() <= 1 for s in (0.0, 0.16, 4.0, 16.0))
check(c8 < 0.2 and r8 < 1e-12 and b8,
      f"sigma continuous in the Zone Hue Edge slider: |sigma_s - sigma_0| <= {c8:.3f} s^2 as s -> 0 (s = 1e-4, 1e-3), at the "
      f"first slider step (Edge 0.01, s 0.16) max {s8:.1e}; periodic (seam {r8:.1e}); in [0, 1] for s in {{0, 0.16, 4, 16}}")
# model: the red width follows C, floored at 10 % of Zone Hue Range Red, and hn is the remap with that width
C8 = np.concatenate([[0.0], np.logspace(-4, 1, 2000)])
lab8 = np.stack([np.full_like(C8, 0.6), C8 * np.cos(0.3), C8 * np.sin(0.3)], axis=1)
wr_ok, hn_err = True, 0.0
for zr in (5.0, 45.0, 180.0):
    for lp in (0.0, 0.5, 1.0):
        for lcm in (0.03, 0.4):
            for e in (0.0, 1.0):
                p8 = {**P0, "zoneHueRed": zr, "zoneHueYellow": 5.0, "hueStrength": 0.99, "lipsProtect": lp,
                      "lipsChromaMin": lcm, "zoneHueEdge": e}
                ex = sm.pixel_core(lab8, p8, ident, ident)[4]
                wr = np.degrees(ex["wR"])
                lo = zr * (1 - 0.9 * lp)
                wr_ok &= bool(np.all(wr >= lo - 1e-9) and np.all(wr <= min(zr, 180.0) + 1e-9) and np.all(np.diff(wr) <= 1e-12)
                              and (lp > 0 or np.all(wr == zr)))
                tg = np.radians(UI["targetHue"] + UI["targetHueTilt"] * (ex["Lc"] - UI["tiltPivot"]))
                d = ex["h"] - tg
                d = d - 2 * np.pi * np.round(d / (2 * np.pi))
                w = blend_w(d, np.radians(5.0), ex["wR"], sm.EDGE_GAIN * e)
                hn_err = max(hn_err, np.abs(fin(ex["hn"], "model hn") - (tg + d - ex["wgt"] * np.sin(d) * np.exp((np.cos(d) - 1) / (w * w)))).max())
check(wr_ok and hn_err < 1e-12, f"model red width: non-increasing in C, within [zoneHueRed (1 - 0.9 Lips Protect), zoneHueRed] "
                                f"deg (no floor on the pixel value), == zoneHueRed exactly at Lips Protect 0; hn == the remap "
                                f"with that width at Edge 0 and 1 (max |diff| {hn_err:.1e})")

# =====================================================================
# 9. Chroma remap at the skin line over the full UI grid
# =====================================================================
# wC = min(chromaStrength * knee(C) * ceil(C) * kH, 0.99), lift 100 (g = tanh f), lips off. kH in [0, 1]
# is constant in C at fixed (L, h) without lips, so kH = 1 (the skin line) is the worst case. The
# chroma tilt and its pivot only move the target: Ct_eff swept over Ct x e^+-1.5 (section 7).


def w_field(C, knee, ceil):
    wk = C**2 / (C**2 + knee**2) if knee > 0 else np.ones_like(C)
    wc = 1.0 / (1.0 + (C / ceil) ** 4)
    return wk * wc


def chroma_remap(C, s, knee, ceil, Ct, pct, kH=1.0):
    wC = np.minimum(s * w_field(C, knee, ceil) * kH, 0.99)
    delta = np.log(1 + pct / 100)
    u = np.log(np.maximum(C, 1e-12) / Ct)          # no branch on C, floor inside the log
    f = u - delta * np.tanh(u / delta) if delta > 1e-4 else u
    return C * np.exp(-wC * np.tanh(f))


C9 = np.linspace(1e-6, 0.6, 200_001)
CT9 = [0.003, 0.005, 0.01, 0.03, 0.06, 0.1, 0.15, 0.2, 0.5, 0.8]
w9, w9_at = 1.0, None
for s in [0.0, 0.5, 0.9, 0.99]:
    for knee in [0.0, 0.01, 0.025, 0.05, 0.1]:
        for ceil in [0.05, 0.1, 0.2, 0.35, 0.5]:
            for Ct in CT9:
                for pct in [0, 1, 10, 30, 60, 100]:
                    m = fin(np.diff(chroma_remap(C9, s, knee, ceil, Ct, pct)) / np.diff(C9), "chroma slope").min()
                    if m < w9:
                        w9, w9_at = m, ((knee, ceil, Ct, pct), s)
s9 = w9_at[1]
check(w9 > 0 and abs(w9 / (1 - s9) - 1) < 0.05,
      f"chroma remap at the skin line monotonic, Chroma Strength x Zone Chroma Min (0 .. 0.1) x Max x Ct_eff {CT9} x "
      f"Tolerance (full UI grid, 200 001 C): min slope {w9:.5f} ~ 1 - s = {1 - s9:.2f} at strength {s9} "
      f"(knee/ceil/Ct/pct {w9_at[0]})")
# the remap must be continuous down to C = 0 (Cn -> 0, no jump, no inversion) with the strongest pull
# towards a target far above the input (knee 0, s 0.99, Ct 0.01, no tolerance)
C0 = np.concatenate([[0.0], np.logspace(-12, -3, 100_001)])
Cn0 = chroma_remap(C0, 0.99, 0.0, 0.35, 0.01, 0)
check(np.all(np.isfinite(Cn0)) and Cn0[0] == 0.0 and Cn0[1] < 1e-11 and np.all(np.diff(Cn0) >= 0),
      f"chroma remap continuous at C -> 0 (no branch): Cn(0) = {Cn0[0]:.1e}, "
      f"Cn(1e-12) = {Cn0[1]:.2e}, non-decreasing on [1e-12, 1e-3] (min step {np.diff(Cn0[1:]).min():.1e})")
# Negative controls: the rejected linear and power pulls invert somewhere in the UI ranges (worst:
# strength 0.99, knee 0, ceiling 0.05, Ct 0.2, i.e. the weight falling steeply while C is still below
# the target); the tanh form stays monotonic on the same grid.
lin_w, pow_w, tanh_w = 1.0, 1.0, 1.0
for s in [0.8, 0.9, 0.99]:
    for knee in [0.0, 0.025, 0.1]:
        for ceil in [0.05, 0.35, 0.5]:
            for Ct in [0.01, 0.06, 0.2]:
                w = np.minimum(s * w_field(C9, knee, ceil), 0.99)
                lin_w = min(lin_w, (np.diff(C9 + w * (Ct - C9)) / np.diff(C9)).min())
                pow_w = min(pow_w, (np.diff(C9 * (Ct / C9) ** w) / np.diff(C9)).min())
                tanh_w = min(tanh_w, fin(np.diff(chroma_remap(C9, s, knee, ceil, Ct, 0)) / np.diff(C9), "chroma slope").min())
check(lin_w < 0 and pow_w < 0 and tanh_w > 0,
      f"negative controls: linear {lin_w:+.3f} and power {pow_w:+.3f} chroma pulls invert; tanh {tanh_w:+.3f} does not")

# =====================================================================
# 10. Chroma remap with Chroma Lift, Lips Protect and Zone Hue Edge
# =====================================================================
# ln Cn = ln C - wC g(f), wC = min(sC * wKnee * wCeil * kH(d, C), 0.99), wL = 1 (a constant factor <= 1
# within an L slice; 1 is the worst case). kH depends on C through the red width
# wR(C) = clamp(zoneHueRed, 1, 180) (1 - 0.9 lipsProtect cL(C)), cL = 1 - 1/(1 + (C / lipsChromaMin)^2):
# swept at fixed hue distances d on both sides of the skin line. Effective target Ct e^k, |k| <= 1.5.


def g_lift(th, lift):
    """Chroma Lift: g = 0.5 (1 + r) th + 0.5 (1 - r) lc, lc = eps ln cosh(th / eps), eps 0.05 (DCTL form)"""
    r = lift * 0.01
    xl = np.abs(th) / sm.LIFT_EPS
    return 0.5 * (1 + r) * th + 0.5 * (1 - r) * (sm.LIFT_EPS * (xl + np.log(1.0 + np.exp(-2.0 * xl)) - np.log(2.0)))


th10 = np.linspace(-1.0, 1.0, 200_001)
lift_ok, slope_ok, sign_ok = True, True, True
for lift in (0.0, 25.0, 50.0, 75.0, 100.0):
    gl = g_lift(th10, lift)
    if lift == 100.0:
        lift_ok = np.array_equal(gl, th10)
    nz = np.abs(th10) > 1e-12
    sign_ok &= bool(np.all(np.sign(gl[nz]) == np.sign(th10[nz])))
    sl = np.diff(gl) / np.diff(th10)
    slope_ok &= bool(sl.min() >= lift * 0.01 - 1e-9 and sl.max() <= 1 + 1e-9)
g0 = g_lift(th10, 0.0)
raise0, ratio03 = -g0[th10 < 0].min(), float(g_lift(np.array([0.3]), 0.0)[0] / 0.3)
check(lift_ok and sign_ok and slope_ok and abs(raise0 - 0.5 * sm.LIFT_EPS * np.log(2)) < 1e-6,
      f"Chroma Lift g(th): == th bit for bit at Lift 100; sign(g) == sign(th) and dg/dth in [r, 1] for Lift "
      f"{{0, 25, 50, 75, 100}} %; at Lift 0 the largest raise is |g| = {raise0:.5f} (= 0.5 eps ln 2) and the pull-down "
      f"keeps g/th = {ratio03:.3f} at th = 0.3")

N10 = 4001
lnC10 = np.linspace(np.log(1e-6), 0.0, N10)
C10 = np.exp(lnC10)
LIFT10 = (0, 25, 50, 100)
CTE10 = [ct * np.exp(k) for ct in (0.01, 0.06, 0.2) for k in (-1.5, 0.0, 1.5)]
G10, G10_at = [], []
for tol in (0, 30, 100):
    delta = np.log(1 + tol / 100)
    for lift in LIFT10:
        for ct in CTE10:
            u = lnC10 - np.log(ct)
            f = u - delta * np.tanh(np.clip(u / delta, -20, 20)) if delta > 1e-4 else u
            G10.append(g_lift(np.tanh(f), lift))
            G10_at.append((tol, lift, round(float(ct), 5)))
G10 = np.array(G10)                                          # (108, N10)


def wR_lips(C, zr, lp, lcm):
    """red width (rad): clamp(zoneHueRed, 1, 180) (1 - 0.9 lipsProtect cL(C)) deg (the DCTL form)"""
    cL = 1 - 1 / (1 + (C / max(lcm, 0.001)) ** 2)
    return np.radians(min(max(zr, 1.0), 180.0) * (1 - 0.9 * lp * cL))


def chroma_sweep(LIPS, edge, strengths, dset):
    worst, at = np.inf, None
    se = sm.EDGE_GAIN * edge
    for s in strengths:
        for knee in (0.001, 0.025, 0.1):
            for ceil in (0.05, 0.35, 0.5):
                wf = C10 * C10 / (C10 * C10 + knee ** 2) / (1 + (C10 / ceil) ** 4)
                for dd in dset:
                    d = np.radians(dd)
                    for zr in (5, 45, 180):
                        for zy in (5, 45, 180):
                            for lp, lcm in LIPS:
                                w = blend_w(d, np.radians(zy), wR_lips(C10, zr, lp, lcm), se)
                                wC = np.minimum(s * wf * np.exp((np.cos(d) - 1) / (w * w)), 0.99)
                                sl = fin(np.diff(lnC10[None, :] - wC[None, :] * G10, axis=1) / np.diff(lnC10), "chroma slope")
                                m = sl.min()
                                if m < worst:
                                    i = np.unravel_index(sl.argmin(), sl.shape)
                                    worst, at = m, dict(chromaStrength=s, zoneChromaMin=knee, zoneChromaMax=ceil, d=dd,
                                                        zoneHueRed=zr, zoneHueYellow=zy, lipsProtect=lp, lipsChromaMin=lcm,
                                                        tol_lift_Cteff=G10_at[i[0]], C=round(float(C10[i[1]]), 5))
    return worst, at


# cross-check of the sweep formula against the model at d = -30 deg (red side), lips on, Edge 0 and 1
p10 = {**P0, "targetChromaTilt": 0.0, "chromaStrength": 0.99, "zoneChromaMin": 0.001, "zoneChromaMax": 0.35,
       "chromaTolerance": 0.0, "lipsProtect": 1.0, "lipsChromaMin": 0.03, "chromaLift": 100.0, "targetChroma": 0.2,
       "zoneHueRed": 180.0, "zoneHueYellow": 5.0}
h10 = np.radians(target_deg(0.6) - 30.0)
lab10 = np.stack([np.full_like(C10, 0.6), C10 * np.cos(h10), C10 * np.sin(h10)], axis=1)
d10 = np.radians(-30.0)
x10 = 0.0
for e in (0.0, 1.0):
    ex10 = sm.pixel_core(lab10, {**p10, "zoneHueEdge": e}, ident, ident)[4]
    w10 = blend_w(d10, np.radians(5.0), wR_lips(C10, 180.0, 1.0, 0.03), sm.EDGE_GAIN * e)
    wC10 = np.minimum(0.99 * C10 ** 2 / (C10 ** 2 + 0.001 ** 2) / (1 + (C10 / 0.35) ** 4) * np.exp((np.cos(d10) - 1) / (w10 * w10)), 0.99)
    x10 = max(x10, np.abs(fin(ex10["wC"] * ex10["g"], "model wC g") - wC10 * np.tanh(lnC10 - np.log(0.2))).max())
check(x10 < 1e-12, f"chroma sweep formula == skinmodel.pixel_core (wC * g on a C ramp at d = -30 deg, Lips Protect 1, "
                   f"Edge 0 and 1): max |diff| {x10:.1e}")
D10 = (0, 10, -10, 30, -30, 60, -60, 120, -120, 180)
D10E = tuple(sorted({sg * dd for dd in (1, 2, 3, 5, 8, 10, 12, 15, 30, 60, 120) for sg in (1, -1)}))
LIPS_ON = [(lp, lcm) for lp in (0.5, 1.0) for lcm in (0.03, 0.06, 0.1, 0.2, 0.4)]
res10 = {"Edge 0, lips off": chroma_sweep([(0.0, 0.1)], 0.0, (0.3, 0.99), D10),
         "Edge 0, lips on": chroma_sweep(LIPS_ON, 0.0, (0.3, 0.99), D10)}
# Edge > 0: d = 0 and 180 are skipped (sigma = 0.5 there for every s) and the hue distances where Edge
# acts (within 15 deg of the target) are sampled densely. Chroma Strength 0.99 only: wC = min(sC wf kH,
# 0.99) with wf, kH <= 1 never reaches the clamp at sC 0.99, so the slope is linear in sC and smaller
# strengths are dominated by 0.99.
s10 = max(abs(float(sm.width_sigma(np.radians(dd), s)) - 0.5) for dd in (0.0, 180.0) for s in (8.0, 16.0))
check(s10 < 1e-14, f"sigma = 0.5 at d = 0 and 180 deg for Edge > 0 (|diff| {s10:.1e}): those distances are the Edge 0 sweep")
for e in (0.5, 1.0):
    res10[f"Edge {e}, lips off and on"] = chroma_sweep([(0.0, 0.1)] + LIPS_ON, e, (0.99,), D10E)
check(min(v[0] for v in res10.values()) > 0,
      f"chroma remap monotonic in C in (0, 1]: Chroma Strength {{0.3, 0.99}} x Lift {LIFT10} % x tolerance {{0, 30, 100}} x "
      f"Ct_eff = {{0.01, 0.06, 0.2}} e^{{-1.5, 0, 1.5}} x Zone Chroma Min/Max x Zone Hue Range Red/Yellow {{5, 45, 180}}^2 x "
      f"Lips Protect {{0, 0.5, 1}} x Lips Chroma Min (5) x d (Edge 0: {D10} deg; Edge 0.5 / 1: {D10E} deg): "
      + "; ".join(f"[{k}] min slope of ln Cn vs ln C {v[0]:.4f} at {v[1]}" for k, v in res10.items()))

# =====================================================================
# 11. 2D Jacobian on the fine grid
# =====================================================================
# Hue weight depends on C (knee / ceiling); chroma weight depends on h (kH): per-axis monotonicity does
# not exclude folds. Work in (ln C, d) with d = h - target: the Cartesian det has the sign of
# det d(ln Cn, hn)/d(ln C, d), ~ (1 - s)(1 - sC) = 1e-4 at the strongest compression point (d = 0, C just
# above the knee). L only moves the target, so one L suffices. Grid: 2001 log steps in C, 3601 in d
# (50 samples per 5 deg kernel width). Zone Hue Edge 0, lips off, lift 100 here; section 12 covers them.
# Mix blends in Cartesian Oklab: a' = (1-mix) a + mix a_F (same for b). The (ln C, d) -> (a, b) Jacobian
# has det C^2 > 0, so det d(a', b')/d(ln C, d) / C^2 is the Cartesian det d(a', b')/d(a, b).
LNC = np.linspace(np.log(1e-4), np.log(0.6), 2001)
D = np.linspace(-np.pi, np.pi, 3601)


def polar_map(s, sC, knee, ceil, Ct, pct, wY_deg, wR_deg):
    """(ln Cn, hn) on the (ln C, d) grid; factors of C only or d only stay 1D and broadcast."""
    C1 = np.exp(LNC)[:, None]                      # (nC, 1)
    d1 = D[None, :]                                # (1, nd)
    wf = w_field(C1, knee, ceil)
    wgt = np.minimum(s * wf, 0.99)
    w = blend_w(d1, np.radians(max(wY_deg, 1.0)), np.radians(max(wR_deg, 1.0)))
    E = np.exp((np.cos(d1) - 1) / (w * w))
    wC = np.minimum(sC * wf * E, 0.99)             # (nC, nd)
    hn = d1 - wgt * np.sin(d1) * E                 # (nC, nd)
    delta = np.log(1 + pct / 100)
    u = np.log(np.maximum(C1, 1e-12) / Ct)
    f = u - delta * np.tanh(u / delta) if delta > 1e-4 else u
    wC *= np.tanh(f)
    lnCn = np.log(C1) - wC
    return lnCn, hn


def jac_det(F, G, X, Y):
    """det d(F, G)/d(X, Y) on the grid (axis 0 = X, axis 1 = Y), two full arrays alive"""
    det = np.gradient(F, X, axis=0)
    det *= np.gradient(G, Y, axis=1)
    t2 = np.gradient(F, Y, axis=1)
    t2 *= np.gradient(G, X, axis=0)
    det -= t2
    return fin(det, "Jacobian det")


def min_det_fine(*args, mixes=()):
    """(min det, max |det(-pi) - det(+pi)|, {mix: min Cartesian det after the Mix blend}). At the seam the
    d derivative is a periodic central difference (D[0] = -pi and D[-1] = +pi are the same hue; hn wraps by
    2 pi), so the two columns differ only through the map's own values at -pi and +pi."""
    lnCn, hn = polar_map(*args)
    dD = D[1] - D[0]
    dl = (lnCn[:, 1] - lnCn[:, -2]) / (2 * dD)
    dh = (hn[:, 1] - hn[:, -2] + 2 * np.pi) / (2 * dD)
    seam = [np.gradient(lnCn[:, c], LNC) * dh - dl * np.gradient(hn[:, c], LNC) for c in (0, -1)]
    dmin = jac_det(lnCn, hn, LNC, D).min()
    out = {}
    if mixes:
        C1, d1 = np.exp(LNC)[:, None], D[None, :]
        Cn = np.exp(lnCn)
        del lnCn
        aF, bF = Cn * np.cos(hn), Cn * np.sin(hn)
        del Cn, hn
        for mix in mixes:
            ap = (1 - mix) * (C1 * np.cos(d1)) + mix * aF
            bp = (1 - mix) * (C1 * np.sin(d1)) + mix * bF
            det = jac_det(ap, bp, LNC, D)
            det /= C1 * C1
            out[mix] = det.min()
    return dmin, fin(np.abs(seam[0] - seam[1]), "Jacobian seam").max(), out


w11, w11_at, seam11, mix11, mix11_at = np.inf, None, 0.0, np.inf, None
eq11 = np.inf                                       # equal widths, strengths 0.99: the strongest point ~1e-4
JOBS11 = [((0.99, 0.99), (w_, w_), (knee, ceil, Ct, pct)) for w_ in (5, 20, 45, 180)
          for knee in (0.0, 0.1) for ceil in (0.05, 0.5) for Ct in (0.01, 0.06, 0.2) for pct in (0, 100)] \
    + [(sp, wp, (knee, ceil, Ct, pct)) for sp in ((0.99, 0.99), (0.5, 0.99))
       for wp in ((5, 180), (180, 5), (20, 45), (5, 60), (60, 5))
       for knee in (0.0, 0.1) for ceil in (0.05, 0.5) for Ct in (0.003, 0.8) for pct in (0, 100)]
for (s_, sC_), (wY_, wR_), (knee, ceil, Ct, pct) in JOBS11:
    mixes = (0.25, 0.5) if wY_ == wR_ and wY_ in (5, 45, 180) and Ct in (0.01, 0.2) else ()
    m, sm11, mx = min_det_fine(s_, sC_, knee, ceil, Ct, pct, wY_, wR_, mixes=mixes)
    seam11 = max(seam11, sm11)
    if wY_ == wR_:
        eq11 = min(eq11, m)
    if m < w11:
        w11, w11_at = m, (s_, sC_, wY_, wR_, knee, ceil, Ct, pct)
    for mix, v in mx.items():
        if v < mix11:
            mix11, mix11_at = v, (mix, knee, ceil, Ct, pct, wY_)
check(w11 > 0, f"2D (ln C, d) map on 2001 x 3601: positive Jacobian det everywhere over {len(JOBS11)} sets (equal widths "
               f"5/20/45/180 and asymmetric pairs, Ct_eff 0.003 .. 0.8, Zone Chroma Min 0 / 0.1, Max 0.05 / 0.5, "
               f"tolerance 0 / 100), min {w11:.2e} at s/sC/wY/wR/knee/ceil/Ct/pct {w11_at}")
check(abs(eq11 - 1e-4) < 2e-5, f"  ... and with equal widths and Strengths 0.99 the minimum {eq11:.3e} is ~(1-s)(1-sC) = 1e-4 "
                               f"(the grid resolves the strongest point)")
check(seam11 < 1e-9, f"2D map periodic at the anti-skin hue: max |det(d = -pi) - det(d = +pi)| {seam11:.1e} < 1e-9")
check(mix11 > 0, f"2D map after the Mix blend in Cartesian Oklab has positive det d(a',b')/d(a,b), "
                 f"min {mix11:.3f} at mix/knee/ceil/Ct/pct/width {mix11_at}")

# =====================================================================
# 12. 2D Jacobian with lips, lift and Zone Hue Edge
# =====================================================================
LNC12 = np.linspace(np.log(1e-4), 0.0, 1001)
D12 = np.linspace(-np.pi, np.pi, 2001)


def det12(lnCn, hn):
    det = jac_det(lnCn, hn, LNC12, D12)
    i = np.unravel_index(det.argmin(), det.shape)
    return det.min(), (round(float(np.exp(LNC12[i[0]])), 5), round(float(np.degrees(D12[i[1]])), 2))


def lnc_lift(C1, wC, Ct, tol, lift):
    delta = np.log(1 + tol / 100)
    u = np.log(C1 / Ct)
    f = u - delta * np.tanh(u / delta) if delta > 1e-4 else u
    return np.log(C1) - wC * g_lift(np.tanh(f), lift)


def min_det12(sC, knee, ceil, Ct, tol, wY_deg, wR_deg, lp, lcm, lift, se, s=0.99):
    """kH and the hue remap share the C-dependent red width and the Zone Hue Edge blend (gain se)."""
    C1 = np.exp(LNC12)[:, None]
    d1 = D12[None, :]
    wz = C1 * C1 / (C1 * C1 + knee ** 2) / (1 + (C1 / ceil) ** 4)          # wKnee * wCeil, wL = 1
    wgt = np.minimum(s * wz, 0.99)
    w = blend_w(d1, np.radians(min(max(wY_deg, 1.0), 180.0)), wR_lips(C1, wR_deg, lp, lcm), se)
    E = np.exp((np.cos(d1) - 1) / (w * w))
    hn = d1 - wgt * np.sin(d1) * E
    return det12(lnc_lift(C1, np.minimum(sC * wz * E, 0.99), Ct, tol, lift), hn)


def min_det_designA(sC, knee, ceil, Ct, tol, wY_deg, wR_deg, lp, lr, off, lcm, lift, s=0.99):
    """negative control: the rejected Design A (a separate lips kernel kL(h) inside the chroma
    weight, wC ~ (1 - lp kL cL), plus a second hue attractor of strength min(lp cL, 0.99))."""
    C1 = np.exp(LNC12)[:, None]
    d1 = D12[None, :]
    wz = C1 * C1 / (C1 * C1 + knee ** 2) / (1 + (C1 / ceil) ** 4)
    wgt = np.minimum(s * wz, 0.99)
    hL, wl2 = np.radians(off), np.radians(lr) ** 2
    cL = 1 - 1 / (1 + (C1 / lcm) ** 2)
    P = lp * np.exp((np.cos(d1 - hL) - 1) / wl2) * cL
    w = blend_w(d1, np.radians(wY_deg), np.radians(wR_deg))
    E = np.exp((np.cos(d1) - 1) / (w * w))
    hn1 = d1 - wgt * np.sin(d1) * E
    sL = np.minimum(lp * cL, 0.99)
    dL = hn1 - hL
    hn = hn1 - sL * np.sin(dL) * np.exp((np.cos(dL) - 1) / wl2)
    return det12(lnc_lift(C1, np.minimum(sC * wz * (1 - P) * E, 0.99), Ct, tol, lift), hn)


BASE12 = [(knee, ceil, Ct, tol, wY_, wR_)
          for knee, ceil, Ct, tol in ((0.001, 0.05, 0.01 * np.exp(-1.5), 0), (0.1, 0.5, 0.2 * np.exp(1.5), 100),
                                      (0.001, 0.5, 0.01 * np.exp(-1.5), 100), (0.001, 0.05, 0.2 * np.exp(1.5), 0))
          for wY_, wR_ in ((5, 180), (180, 5), (45, 45), (180, 45))]
LIPS12 = [("lips off", (0.0, 0.1)), ("Lips Protect 1, min 0.06", (1.0, 0.06)), ("Lips Protect 1, min 0.4", (1.0, 0.4)),
          ("Lips Protect 0.5, min 0.1", (0.5, 0.1)), ("Lips Protect 1, min 0.03", (1.0, 0.03))]
for e in EDGES:
    res = {}
    for lname, (lp, lcm) in LIPS12:
        for lift in (0, 100):
            for knee, ceil, Ct, tol, wY_, wR_ in BASE12:
                m, where = min_det12(0.99, knee, ceil, Ct, tol, wY_, wR_, lp, lcm, lift, sm.EDGE_GAIN * e)
                if m < res.get(lname, (np.inf,))[0]:
                    res[lname] = (m, (lift, knee, ceil, round(float(Ct), 5), tol, wY_, wR_), where)
    check(min(v[0] for v in res.values()) > 0,
          f"2D (ln C, d) map, Strengths 0.99, Zone Hue Edge {e}: Jacobian det > 0 on 1001 x 2001, {len(BASE12)} sets x Lift "
          f"{{0, 100}} x {len(LIPS12)} lips variants: " + "; ".join(f"[{ln}] min {v[0]:.3e} at lift/knee/ceil/Ct_eff/tol/wY/wR "
                                                                     f"{v[1]}, (C, d deg) {v[2]}" for ln, v in res.items()))


# The grid minimum is not the infimum: at d = 0, C = Ct (tolerance 0, field ~1) the det is ~(1 - s)(1 - sC) = 1e-4.
def det_at(C0, sC, knee, ceil, Ct, tol, lift, s=0.99, e=1e-5):
    """det d(ln Cn, hn)/d(ln C, d) at (C0, d = 0) by central differences (d = 0: the kernel is 1, w drops out)"""
    def f(lnc, d):
        C1 = np.exp(lnc)
        wz = C1 * C1 / (C1 * C1 + knee ** 2) / (1 + (C1 / ceil) ** 4)
        E = np.exp((np.cos(d) - 1) / np.radians(45.0) ** 2)
        return lnc_lift(C1, min(sC * wz * E, 0.99), Ct, tol, lift), d - min(s * wz, 0.99) * np.sin(d) * E
    l0 = np.log(C0)
    a1, b1 = f(l0 + e, 0.0); a0, b0 = f(l0 - e, 0.0); a2, b2 = f(l0, e); a3, b3 = f(l0, -e)   # noqa: E702
    return ((a1 - a0) * (b2 - b3) - (a2 - a3) * (b1 - b0)) / (4 * e * e)


inf12 = det_at(0.06, 0.99, 0.001, 0.5, 0.06, 0, 100)
check(1e-4 * (1 - 1e-9) < inf12 < 1.2e-4, f"2D det at the strongest point d = 0, C = Ct = 0.06 (tolerance 0, Zone Chroma Min "
                                          f"0.001, Max 0.5, Strengths 0.99, Lift 100): {inf12:.3e}, just above the infimum "
                                          f"(1 - s)(1 - sC) = 1e-4; the grid minima above are coarser than this point")
mA, whereA = min_det_designA(0.99, 0.001, 0.05, 0.2 * np.exp(1.5), 0, 5, 180, 1.0, 10, -24, 0.06, 100)
check(mA < 0, f"negative control: the rejected Design A (separate lips kernel inside the chroma weight + second hue "
              f"attractor; Lips Protect 1, range 10 deg at -24 deg, min 0.06, Lift 100, knee 0.001, ceiling 0.05, Ct_eff 0.896, "
              f"tol 0, ranges 5/180) folds: min det {mA:+.3f} at (C, d deg) {whereA}; why lips narrow the red range instead")

# =====================================================================
# 13. Zone alpha a = wField * kH
# =====================================================================


def zone_a(lab, p):
    """zone weight a = wField * kH from Oklab rows (skinmodel.pixel_core)"""
    return fin(sm.pixel_core(lab, p, ident, ident)[3], "zone alpha")


def lab_grid(Ls, Cs, hs):
    Lg_, Cg_, hg_ = np.meshgrid(Ls, Cs, hs, indexing="ij")
    return np.stack([Lg_.ravel(), (Cg_ * np.cos(hg_)).ravel(), (Cg_ * np.sin(hg_)).ravel()], axis=1)


LAB13 = lab_grid(np.linspace(0.0, 1.1, 12), np.concatenate([[0.0], np.linspace(1e-4, 0.6, 120)]),
                 np.linspace(-np.pi, np.pi, 721))
amin, amax = np.inf, -np.inf
for wY_ in W8A:
    for wR_ in W8A:
        a13 = zone_a(LAB13, {**P0, "zoneHueYellow": float(wY_), "zoneHueRed": float(wR_)})
        amin, amax = min(amin, a13.min()), max(amax, a13.max())
for knee in [0.001, 0.01, 0.025, 0.1]:
    for ceil in [0.05, 0.35, 0.5]:
        a13 = zone_a(LAB13, {**P0, "zoneChromaMin": knee, "zoneChromaMax": ceil})
        amin, amax = min(amin, a13.min()), max(amax, a13.max())
del a13, LAB13
check(0.0 <= amin and amax <= 1.0,
      f"zone alpha in [0, 1] on 1 048 572 (L, C, h) points x ({len(W8A)}^2 width pairs + 12 knee/ceiling, knee >= 0.001): "
      f"min {amin:.3e}, max {amax:.6f}")

h13 = np.linspace(-np.pi, np.pi, 20_000)
step13 = h13[1] - h13[0]
da13, da13_at = 0.0, None
for L_ in (0.2, 0.6, 1.0):
    for C_ in (0.02, 0.06, 0.2):
        lab_h = np.stack([np.full_like(h13, L_), C_ * np.cos(h13), C_ * np.sin(h13)], axis=1)
        for wY_ in W8A:
            for wR_ in W8A:
                ah = zone_a(lab_h, {**P0, "zoneHueYellow": float(wY_), "zoneHueRed": float(wR_)})
                m = max(np.abs(np.diff(ah)).max(), abs(ah[0] - ah[-1]))     # include the wrap h = -pi -> +pi
                if m > da13:
                    da13, da13_at = m, (L_, C_, wY_, wR_)
# Bound: |dkH/dd| <= 1 / (w_min sqrt(e)) for the Gaussian-like kernel at width 5 deg; 2x margin for the blend.
bound13 = 2 * step13 / (np.radians(5.0) * np.sqrt(np.e))
check(da13 < bound13, f"zone alpha continuous in hue: max |a(h + dh) - a(h)| {da13:.2e} < {bound13:.2e} "
                      f"(dh = {step13:.2e} rad, 20 000 points; worst at L/C/zoneHueYellow/zoneHueRed {da13_at})")
Cp = np.linspace(1e-4, 0.6, 2001)
seam13 = 0.0
for e in (0.0, 1.0):
    for wY_ in W8A:
        for wR_ in W8A:
            wf = w_field(Cp, 0.025, 0.35)
            apm = [fin(wf * np.exp((np.cos(dd) - 1) / blend_w(dd, np.radians(wY_), np.radians(wR_), sm.EDGE_GAIN * e) ** 2),
                       "alpha seam") for dd in (np.pi, -np.pi)]
            seam13 = max(seam13, np.abs(apm[0] - apm[1]).max())
check(seam13 <= 1e-12, f"zone alpha periodic at d = +-pi (Edge 0 and 1): max |a(-pi) - a(+pi)| {seam13:.1e} <= 1e-12 (float64)")
grey = np.array([[0.1, 0.0, 0.0], [0.6, 0.0, 0.0], [1.0, 0.0, 0.0]])
a_k0 = zone_a(grey, {**P0, "zoneChromaMin": 0.0})
a_ring = zone_a(lab_grid([0.6], [1e-9], np.linspace(-np.pi, np.pi, 361)), {**P0, "zoneChromaMin": 0.0})
print(f"info Zone Chroma Min 0 (below the UI minimum 0.001): greys a = {np.round(a_k0, 4).tolist()}, "
      f"around C = 1e-9 a spans [{a_ring.min():.3f}, {a_ring.max():.3f}]: direction-dependent at C = 0")

# with and without Zone Hue Edge, luma window and lips
p13 = {**P0, "zoneLumaWindow": 1, "zoneLumaMin": 0.2, "zoneLumaMax": 0.9, "lipsProtect": 1.0, "lipsChromaMin": 0.03}
LAB13W = lab_grid(np.linspace(-0.2, 1.4, 17), np.concatenate([[0.0], np.linspace(1e-4, 0.6, 60)]), np.linspace(-np.pi, np.pi, 361))
L13g = np.linspace(-0.5, 2.0, 20_000)
bh13 = 2 * step13 / (np.radians(1.0) * np.sqrt(np.e))   # narrowest width the lips shrink can reach: 1 deg
# window edges + target tilt (12 deg / L) through kH (red width >= 4.5)
bl13 = 2 * (L13g[1] - L13g[0]) * (2 / 0.2 + 2 / 0.9 + np.radians(12.0) / (np.radians(4.5) * np.sqrt(np.e)))
tg13 = np.radians(target_deg(0.6))
for e in (0.0, 1.0):
    pe = {**p13, "zoneHueEdge": e}
    amin, amax = np.inf, -np.inf
    for ch in ({}, {"zoneHueYellow": 5.0, "zoneHueRed": 180.0}, {"zoneLumaMin": 0.0, "zoneLumaMax": 0.3},
               {"zoneLumaMin": 0.8, "zoneLumaMax": 1.5}, {"lipsChromaMin": 0.4, "zoneHueRed": 5.0}):
        a13 = zone_a(LAB13W, {**pe, **ch})
        amin, amax = min(amin, a13.min()), max(amax, a13.max())
    check(0.0 <= amin and amax <= 1.0, f"zone alpha (Edge {e}, window on, lips on) in [0, 1] on {len(LAB13W)} (L, C, h) points "
                                       f"x 5 sets: [{amin:.2e}, {amax:.6f}]")
    dh13, dl13 = 0.0, 0.0
    for L_ in (0.15, 0.2, 0.6, 0.9):
        for C_ in (0.03, 0.06, 0.2):
            lab_h = np.stack([np.full_like(h13, L_), C_ * np.cos(h13), C_ * np.sin(h13)], axis=1)
            ah = zone_a(lab_h, {**pe, "zoneHueYellow": 5.0, "zoneHueRed": 180.0})
            dh13 = max(dh13, np.abs(np.diff(ah)).max(), abs(ah[0] - ah[-1]))
    for hh in np.radians([20.0, 44.0, 70.0]):
        lab_L = np.stack([L13g, 0.06 * np.cos(hh) * np.ones_like(L13g), 0.06 * np.sin(hh) * np.ones_like(L13g)], axis=1)
        dl13 = max(dl13, np.abs(np.diff(zone_a(lab_L, pe))).max())
    check(dh13 < bh13 and dl13 < bl13, f"zone alpha (Edge {e}, window and lips on) continuous: in hue max step {dh13:.2e} < "
                                       f"{bh13:.2e} (20 000 points), in L max step {dl13:.2e} < {bl13:.2e} (20 000 points on L in [-0.5, 2])")
    # continuity and C1 in C on chroma ramps through the lips region: halving the C step must halve the
    # largest jump of the finite-difference derivative (a kink keeps it constant: a clamp on the red width
    # after the lips shrink, max(zoneHueRed (1 - 0.9 P cL), 1), had one at C 0.0849 for Red 5, Protect 1, min 0.03).
    c1, st = [], 0.0
    for pz, dd in [({"zoneHueRed": 5.0, "lipsProtect": 1.0, "lipsChromaMin": 0.03}, -1.0),
                   ({"zoneHueRed": 5.0, "lipsProtect": 1.0, "lipsChromaMin": 0.03}, -30.0),
                   ({"lipsProtect": 1.0, "lipsChromaMin": 0.06}, -15.0), ({}, -30.0), ({}, 20.0)]:
        jumps = []
        for n in (40_001, 80_001):
            Cr = np.linspace(0.005, 0.4, n)
            hh = tg13 + np.radians(dd)
            ar = zone_a(np.stack([np.full_like(Cr, 0.6), Cr * np.cos(hh), Cr * np.sin(hh)], axis=1), {**P0, "zoneHueEdge": e, **pz})
            jumps.append(np.abs(np.diff(ar, 2)).max() / (Cr[1] - Cr[0]))
            if n == 40_001:
                st = max(st, np.abs(np.diff(ar)).max())
        c1.append(jumps[1] / jumps[0])
    check(max(c1) < 0.6 and st < 1e-3,
          f"zone alpha (Edge {e}) continuous and C1 in C (C in [0.005, 0.4], L 0.6; Red 5 / Protect 1 / min 0.03 at d -1 and "
          f"-30 deg, Protect 1 / min 0.06 at -15 deg, defaults at -30 and +20 deg): max step {st:.2e}, derivative-jump ratio "
          f"when halving the step {[round(float(r), 3) for r in c1]} < 0.6 (0.5 = smooth, ~1 = kink)")
    a_grey = max(zone_a(grey, {**pe, "zoneChromaMin": k}).max() for k in (0.001, 0.025, 0.1))
    a_grey0 = max(zone_a(grey, {**P0, "zoneHueEdge": e, "zoneChromaMin": k}).max() for k in (0.001, 0.025, 0.1))
    check(a_grey == 0.0 and a_grey0 == 0.0, f"zone alpha == 0 on the neutral axis (C = 0) for Zone Chroma Min in [0.001, 0.1], "
                                            f"Edge {e}, window and lips off / on (max {max(a_grey, a_grey0):.1e})")
del LAB13W, a13
# alpha hue gradient near the anti-target (|d| > 150 deg), Edge 1 vs Edge 0, same params (a seam detector)
ga13 = []
for zy, zr in ((180.0, 45.0), (90.0, 20.0), (180.0, 5.0)):
    for L_ in (0.6, 0.9):
        for C_ in (0.06, 0.2):
            hh = np.radians(target_deg(L_)) + h13
            lab_h = np.stack([np.full_like(hh, L_), C_ * np.cos(hh), C_ * np.sin(hh)], axis=1)
            far = np.abs(h13) > np.radians(150.0)
            pa = {**p13, "zoneHueYellow": zy, "zoneHueRed": zr}
            g1 = np.abs(np.gradient(zone_a(lab_h, {**pa, "zoneHueEdge": 1.0}), h13))[far].max()
            g0_ = np.abs(np.gradient(zone_a(lab_h, {**pa, "zoneHueEdge": 0.0}), h13))[far].max()
            ga13.append((g1 / g0_ if g0_ > 0 else (1.0 if g1 == 0 else np.inf), zy, zr, L_, C_, g1, g0_))
wg13 = max(ga13)
check(wg13[0] <= 1.3, f"zone alpha (window and lips on) hue gradient over |d| > 150 deg at Edge 1 <= 1.3 x Edge 0: worst ratio "
                      f"{wg13[0]:.3f} at Yellow/Red {wg13[1:3]}, L {wg13[3]}, C {wg13[4]} ({wg13[5]:.3g} vs {wg13[6]:.3g} per rad; "
                      f"widths 180/45, 90/20, 180/5 x L 0.6/0.9 x C 0.06/0.2)")

# independence of Strength, Lift, Mix and Show Shift (model, codes) and the Zone Luma Window factors
x11 = np.vstack([np.random.default_rng(11).uniform(0, 1.0, (20_000, 3)),
                 cct_enc(np.array([AP0_AP1 @ np.array(v) for v in cc.values()]))])
alpha_rnd = np.random.default_rng(28).uniform(0, 1, len(x11))
indep = True
for base in (P0, {**p13, "zoneHueEdge": 1.0}):
    ref = sm.model(x11, TEXT, base, NAME)[1]
    indep &= all(np.array_equal(sm.model(x11, TEXT, {**base, **ch}, NAME)[1], ref)
                 for ch in ({"hueStrength": 0.0}, {"hueStrength": 0.99}, {"chromaStrength": 0.0}, {"chromaStrength": 0.99},
                            {"chromaLift": 0.0}, {"mix": 0.0}, {"mix": 0.37}, {"showShift": 1}))
check(indep, "zone alpha identical (bit-for-bit) for Hue / Chroma Strength 0 / 0.99, Chroma Lift 0, Mix 0 / 0.37, Show Shift "
             "on (defaults; Edge 1 with window and lips on)")
Lc13 = clamp_L(np.linspace(-1.0, 3.0, 40_001))
wl_ok = True
for mn in (0.0, 0.1, 0.4, 0.8):
    for mx in (0.3, 1.1, 1.5):
        kn = Lc13 ** 8 / (Lc13 ** 8 + mn ** 8) if mn > 0 else np.ones_like(Lc13)
        wl = fin(kn * (1 / (1 + (Lc13 / mx) ** 8)), "luma window")
        wl_ok &= bool(wl.min() > 0 and wl.max() <= 1)
LABW = lab_grid(np.linspace(-0.2, 1.4, 17), np.linspace(1e-4, 0.6, 20), np.linspace(-np.pi, np.pi, 37))
ex13 = sm.pixel_core(LABW, p13, ident, ident)[4]
wl_model = ex13["Lc"] ** 8 / (ex13["Lc"] ** 8 + 0.2 ** 8) * (1 / (1 + (ex13["Lc"] / max(0.9, 0.01)) ** 8))
check(wl_ok and np.abs(ex13["wL"] - wl_model).max() < 1e-15,
      f"Zone Luma Window wL in (0, 1] for Min {{0, 0.1, 0.4, 0.8}} x Max {{0.3, 1.1, 1.5}} on L in [-1, 3]; model wL == the formula")
print(f"info the product wL at Lc = Min is 0.5 * 1/(1 + (Min/Max)^8), e.g. Min 0.1 / Max 1.1: "
      f"{0.5 / (1 + (0.1 / 1.1) ** 8):.10f}; at Min 0.8 / Max 1.1: {0.5 / (1 + (0.8 / 1.1) ** 8):.4f}")

# =====================================================================
# 14. Show Shift: false colour of the move
# =====================================================================
SETS = {
    "defaults": dict(P0),
    "flat chroma target": {**P0, "targetChromaTilt": 0.0},
    "extreme": {**P0, "hueStrength": 0.99, "chromaStrength": 0.99, "zoneHueYellow": 20.0, "zoneHueRed": 20.0,
                "targetHueTilt": 60.0, "chromaTolerance": 0.0, "zoneChromaMin": 0.001, "zoneChromaMax": 0.05, "mix": 0.5},
    "asymmetric extreme": {**P0, "hueStrength": 0.99, "chromaStrength": 0.99, "zoneHueYellow": 5.0, "zoneHueRed": 180.0,
                           "targetChromaTilt": -150.0, "targetHueTilt": -60.0, "chromaTolerance": 0.0, "zoneChromaMin": 0.001,
                           "zoneChromaMax": 0.05, "mix": 0.5},
    "everything": {**P0, "zoneHueEdge": 1.0, "lipsProtect": 1.0, "lipsChromaMin": 0.06, "zoneHueYellow": 180.0,
                   "zoneHueRed": 5.0, "hueStrength": 0.99, "chromaStrength": 0.99, "chromaLift": 0.0, "zoneLumaWindow": 1,
                   "zoneLumaMin": 0.2, "zoneLumaMax": 1.2, "tiltPivot": 0.4, "mix": 0.6},
    "mix 0": {**P0, "mix": 0.0},
}


def shift_of(codes, p, i):
    return fin(sm.model(codes, TEXT, {**p, "workingSpace": i, "showShift": 1}, NAME)[0], "Show Shift")


lo14, hi14 = np.inf, -np.inf
for p in SETS.values():
    for i in range(len(WS_ORDER)):
        o = shift_of(x11, p, i)
        lo14, hi14 = min(lo14, o[:, :2].min()), max(hi14, o[:, :2].max())
check(0.0 <= lo14 and hi14 <= 1.0, f"Show Shift R, G in [0, 1] on {len(SETS)} parameter sets x 6 spaces: [{lo14:.3f}, {hi14:.3f}]")
o_full = shift_of(x11, {**P0, "hueStrength": 0.99, "chromaStrength": 0.99, "zoneHueYellow": 180.0, "zoneHueRed": 180.0,
                        "chromaTolerance": 0.0, "zoneChromaMin": 0.001, "zoneChromaMax": 0.5}, 0)
print(f"info Show Shift is not clamped: Strengths 0.99, ranges 180/180, tolerance 0, Mix 1 gives R in "
      f"[{o_full[:, 0].min():.3f}, {o_full[:, 0].max():.3f}], G in [{o_full[:, 1].min():.3f}, {o_full[:, 1].max():.3f}]")
# With Mix 1, Show Shift equals the actual move of labn (hue turn and ln chroma ratio measured on the
# output Oklab); with Mix < 1 it is the commanded move x Mix.
real14, n14 = 0.0, 0
REAL14 = [{**p, "mix": 1.0} for p in SETS.values()] + [
    {**P0, "chromaLift": lift, "lipsProtect": 1.0, "zoneLumaWindow": 1, "chromaStrength": 0.9, "hueStrength": 0.9,
     "zoneHueEdge": e, "mix": 1.0} for lift in (0.0, 50.0, 100.0) for e in (0.0, 1.0)]
for p in REAL14:
    for i, ws in enumerate(WS_ORDER):
        enc, dec, _ = CURVES[ws]
        mat = WS_MAT[ws]
        o, _, inf = sm.pixel(x11, {**p, "showShift": 1}, dec, enc, lambda r, m=mat: to_lab(r, m), lambda l, m=mat: from_lab(l, m))
        fin(o, "Show Shift"), fin(inf["labn"], "labn")
        Ci, Co = np.hypot(inf["lab"][:, 1], inf["lab"][:, 2]), np.hypot(inf["labn"][:, 1], inf["labn"][:, 2])
        dhr = np.arctan2(inf["labn"][:, 2], inf["labn"][:, 1]) - np.arctan2(inf["lab"][:, 2], inf["lab"][:, 1])
        dhr = dhr - 2 * np.pi * np.round(dhr / (2 * np.pi))
        ok = Ci > 1e-6
        real14 = max(real14, np.abs(o[:, 1] - (0.5 + np.log(Co / Ci)))[ok].max(),
                     np.abs(o[:, 0] - (0.5 + np.degrees(dhr) / 60.0))[ok].max())
        n14 += 1
check(real14 <= 1e-9, f"Show Shift at Mix 1 == actual move of labn (R vs real hue turn deg/60, G vs ln(C_out/C), C > 1e-6): "
                      f"max |diff| {real14:.1e} <= 1e-9 ({n14} runs: {len(SETS)} sets + Lift {{0, 50, 100}} x Edge {{0, 1}} with "
                      f"lips and window on, x 6 spaces)")
mix0_ok, s0_r, s0_gb_ok = True, 0.0, True
for i in range(len(WS_ORDER)):
    for p in SETS.values():
        mix0_ok &= bool(np.all(shift_of(x11, {**p, "mix": 0.0}, i) == 0.5))
    o = shift_of(x11, {**P0, "hueStrength": 0.0, "chromaStrength": 0.0}, i)
    s0_r = max(s0_r, np.abs(o[:, 0] - 0.5).max())
    s0_gb_ok &= bool(np.all(o[:, 1:] == 0.5))
check(mix0_ok, f"Show Shift at Mix 0 is exactly (0.5, 0.5, 0.5) ({len(SETS)} sets x 6 spaces)")
check(s0_gb_ok and s0_r <= 1e-12, f"Show Shift at Hue and Chroma Strength 0: G, B exactly 0.5; |R - 0.5| {s0_r:.1e} <= 1e-12 "
                                  f"(float64 rounding of hn - h, not exactly 0)")
# Sign and continuity on a hue sweep around the target (d = h - target in [-pi, pi]).
d14 = np.linspace(-np.pi, np.pi, 20_000)
sign_ok, dR14, dG14, seam14 = True, 0.0, 0.0, 0.0
for L_ in (0.3, 0.6, 0.9):
    tgt = np.radians(target_deg(L_))
    for C_ in (0.03, 0.06, 0.15):
        lab14 = np.stack([np.full_like(d14, L_), C_ * np.cos(tgt + d14), C_ * np.sin(tgt + d14)], axis=1)
        for wY_, wR_ in [(45, 45), (5, 180), (180, 5), (20, 60)]:
            for e in (0.0, 1.0):
                pz = {**P0, "zoneHueYellow": float(wY_), "zoneHueRed": float(wR_), "zoneHueEdge": e, "showShift": 1}
                o, _, _ = sm.pixel(lab14, pz, ident, ident, ident, ident)
                R = fin(o, "Show Shift")[:, 0]
                moving = np.abs(R - 0.5) > 1e-9
                sign_ok &= bool(np.all(np.sign(R[moving] - 0.5) == -np.sign(d14[moving])))   # attractor: pulled back towards d = 0
                dR14 = max(dR14, np.abs(np.diff(R)).max())
                dG14 = max(dG14, np.abs(np.diff(o[:, 1])).max())
                seam14 = max(seam14, np.abs(o[0, :2] - o[-1, :2]).max())
check(sign_ok, "Show Shift: R - 0.5 has the sign of the hue shift, opposite to d (attractor): pixels on the yellow "
              "side (d > 0) turn towards red, R < 0.5; on the red side (d < 0) towards yellow, R > 0.5 (Edge 0 and 1)")
check(dR14 < 5e-3 and dG14 < 5e-3, f"Show Shift continuous in hue (20 000 points): max |dR| {dR14:.2e}, max |dG| {dG14:.2e} < 5e-3")
check(seam14 <= 1e-12, f"Show Shift periodic at d = +-pi: max |out(-pi) - out(+pi)| {seam14:.1e} <= 1e-12 (float64)")

# =====================================================================
# 15. Alpha out = a * input alpha (on), input alpha (off)
# =====================================================================
a_ref15 = [sm.pixel(x11, {**P0, "workingSpace": i}, CURVES[ws][1], CURVES[ws][0],
                    lambda r, m=WS_MAT[ws]: to_lab(r, m), lambda l, m=WS_MAT[ws]: from_lab(l, m))[2]["a"]
           for i, ws in enumerate(WS_ORDER)]
on15, one15, off15 = True, True, True
for show in (0, 1):
    for i in range(len(WS_ORDER)):
        for ain in [np.full(len(x11), av) for av in (0.0, 0.25, 0.5, 1.0)] + [alpha_rnd]:
            _, a_on = sm.model(x11, TEXT, {**P0, "showShift": show, "workingSpace": i}, NAME, alpha=ain)
            on15 &= np.array_equal(a_on, a_ref15[i] * ain)
            if np.all(ain == 1.0):
                one15 &= np.array_equal(a_on, a_ref15[i])
            _, a_off = sm.model(x11, TEXT, {**P0, "outputAlpha": 0, "showShift": show, "workingSpace": i}, NAME, alpha=ain)
            off15 &= np.array_equal(a_off, ain)
check(on15, "Output Zone Alpha on: output alpha == a * input alpha bit-for-bit (float64), input alpha {0, 0.25, 0.5, 1} "
            "and random, Show Shift on/off, 6 spaces")
check(one15, "Output Zone Alpha on, input alpha 1: output alpha == a exactly")
check(off15, "Output Zone Alpha off: output alpha == input alpha bit-for-bit (same inputs)")

# =====================================================================
# 16. Zone Hue Edge: negative control, motivation, anti-target smoothness
# =====================================================================
XD16 = np.linspace(-np.pi, np.pi, 200_001)
FAR16 = np.abs(XD16) > np.radians(150.0)


def sig_tanh(d, s):
    """rejected draft: sigS = 0.5 (1 + tanh(s sin d) / tanh(s)), no window (sharp at sin d = 0, so also at d = +-pi)"""
    return 0.5 * (1 + np.tanh(s * np.sin(d)) / np.tanh(s)) if s > 0 else 0.5 * (1 + np.sin(d))


def anti_slope(sigfn, s, wY_deg, wR_deg):
    """max |dkH/dd| over |d| > 150 deg for a width blend sigfn(d, s)"""
    w = np.radians(wR_deg) + (np.radians(wY_deg) - np.radians(wR_deg)) * sigfn(XD16, s)
    return fin(np.abs(np.gradient(np.exp((np.cos(XD16) - 1) / (w * w)), XD16)), "kernel gradient")[FAR16].max()


g16_0, g16_t = anti_slope(sm.width_sigma, 0.0, 180.0, 45.0), anti_slope(sig_tanh, sm.EDGE_GAIN, 180.0, 45.0)
check(g16_t > 5 * g16_0, f"negative control: the pure tanh blend (no (1 + cos d)/2 window) at Edge 1, widths 180/45, has "
                         f"max |dkH/dd| over |d| > 150 deg = {g16_t:.2f} per rad vs Edge 0 {g16_0:.2f} ({g16_t / g16_0:.1f} x > 5 x): "
                         f"a sharp seam at the anti-target hue; why the window")


def kH16(d_deg, s, wY_deg=45.0, wR_deg=4.5):
    d = np.radians(d_deg)
    w = blend_w(d, np.radians(wY_deg), np.radians(wR_deg), s)
    return float(np.exp((np.cos(d) - 1) / (w * w)))


k16 = {(dd, s): kH16(dd, s) for dd in (-15.0, -5.0) for s in (0.0, 8.0, 16.0)}
lab16 = np.array([[0.6, 0.06 * np.cos(np.radians(UI["targetHue"] - 15.0)), 0.06 * np.sin(np.radians(UI["targetHue"] - 15.0))]])
pm16 = {**P0, "targetHueTilt": 0.0, "zoneHueRed": 4.5, "zoneHueYellow": 45.0, "zoneChromaMin": 0.001, "zoneChromaMax": 0.5}
km16 = [float(sm.pixel_core(lab16, {**pm16, "zoneHueEdge": e}, ident, ident)[4]["kH"][0]) for e in (0.0, 0.5, 1.0)]
check(abs(km16[0] - k16[(-15.0, 0.0)]) < 1e-12 and abs(km16[1] - k16[(-15.0, 8.0)]) < 1e-12
      and abs(km16[2] - k16[(-15.0, 16.0)]) < 1e-12 and abs(k16[(-15.0, 0.0)] - 0.745) < 5e-4,
      f"Zone Hue Edge motivation (wY 45, wR 4.5 deg = Red 45 at the Lips Protect 1 floor): hue kernel kH at d = -15 deg is "
      f"{k16[(-15.0, 0.0)]:.3f} at Edge 0, {k16[(-15.0, 8.0)]:.3f} at Edge 0.5, {k16[(-15.0, 16.0)]:.3f} "
      f"at Edge 1; at d = -5 deg {k16[(-5.0, 0.0)]:.3f} / {k16[(-5.0, 8.0)]:.3f} / {k16[(-5.0, 16.0)]:.3f}; the model "
      f"agrees ({km16[0]:.3f}, {km16[1]:.3f}, {km16[2]:.3f})")
r16, at16, rows16 = 0.0, None, []
for wy, wr in ((180.0, 45.0), (90.0, 20.0), (180.0, 5.0), (45.0, 4.5)):
    g0_ = anti_slope(sm.width_sigma, 0.0, wy, wr)
    for e in (0.5, 1.0):
        for nm, fn in [("model", sm.width_sigma)] + [(f"DCTL site {k + 1}", f) for k, f in enumerate(SIGFN) if f]:
            g = anti_slope(fn, sm.EDGE_GAIN * e, wy, wr)
            if nm == "model":
                rows16.append(f"{wy:g}/{wr:g} Edge {e}: {g:.3f} vs {g0_:.3f}")
            if g / g0_ > r16:
                r16, at16 = g / g0_, (wy, wr, e, nm)
check(len(SIGFN) == 2 and all(SIGFN) and r16 <= 1.3,
      f"anti-target smoothness: max |dkH/dd| over |d| > 150 deg <= 1.3 x Edge 0 for widths 180/45, 90/20, 180/5, 45/4.5 x Edge "
      f"{{0.5, 1}}, model and both DCTL sigma statements: worst ratio {r16:.3f} at {at16}; per rad " + "; ".join(rows16))

# =====================================================================
# 17. Defaults: effect on the ColorChecker skin and monotonicity in absolute hue
# =====================================================================
cc_cct = cct_enc(np.array([AP0_AP1 @ np.array(v) for v in cc.values()]))
_, al17, inf17 = sm.pixel(cc_cct, P0, cct_dec, cct_enc, to_lab, from_lab)
rows17, ok17 = [], True
for k, name in enumerate(cc):
    lab_i, lab_o = inf17["lab"][k], inf17["labn"][k]
    h_i = np.degrees(np.arctan2(lab_i[2], lab_i[1]))
    h_o = np.degrees(np.arctan2(lab_o[2], lab_o[1]))
    tgt = UI["targetHue"] + UI["targetHueTilt"] * (float(inf17["ex"]["Lc"][k]) - UI["tiltPivot"])
    lab_rt = to_lab(cct_dec(cct_enc(inf17["outl"][k:k + 1])))[0]          # through the output codes
    dL, dLrt = abs(lab_o[0] - lab_i[0]), abs(lab_rt[0] - lab_i[0])
    ok17 &= h_o > h_i and h_o < tgt and dL <= 1e-9 and 0.0 <= al17[k] <= 1.0
    rows17.append(f"{name}: L {lab_i[0]:.3f}, h {h_i:.2f} -> {h_o:.2f} deg ({h_o - h_i:+.2f}; tilted target {tgt:.2f}), "
                  f"C {np.hypot(*lab_i[1:]):.4f} -> {np.hypot(*lab_o[1:]):.4f}, |dL| model {dL:.1e} / via codes {dLrt:.1e}, "
                  f"alpha {al17[k]:.4f}")
check(ok17, f"defaults (Target Hue {UI['targetHue']:g}) on the ColorChecker skin (ACEScct): hue moves up towards the tilted "
            f"target without passing it, Oklab L unchanged (model, <= 1e-9), alpha in [0, 1]:\n     " + "\n     ".join(rows17))
# sections 8-12 work in d = h - target, so they hold for any target; here the defaults in absolute hue
H17 = np.linspace(-np.pi, np.pi, 3601)
LNC17 = np.linspace(np.log(1e-3), np.log(0.5), 201)
sl17, det17, rows17 = np.inf, np.inf, []
for L_ in (0.3, 0.6, 0.9):
    Cg, Hg = np.meshgrid(np.exp(LNC17), H17, indexing="ij")
    lab17 = np.stack([np.full(Cg.size, L_), (Cg * np.cos(Hg)).ravel(), (Cg * np.sin(Hg)).ravel()], axis=1)
    _, _, labn17, _, ex17 = sm.pixel_core(lab17, P0, ident, ident)
    hn = np.unwrap(fin(ex17["hn"], "model hn").reshape(Cg.shape), axis=1)
    lnCn = fin(np.log(np.hypot(labn17[:, 1], labn17[:, 2])), "model ln Cn").reshape(Cg.shape)
    wgt = ex17["wgt"].reshape(Cg.shape)[:, 0]
    slm = (np.diff(hn, axis=1) / np.diff(H17)[None, :] - (1 - wgt)[:, None]).min()
    det = jac_det(lnCn, hn, LNC17, H17)
    sl17, det17 = min(sl17, slm), min(det17, det.min())
    rows17.append(f"L {L_}: min(slope - (1 - wgt)) {slm:.2e}, min det {det.min():.3e}")
    del lab17, labn17, ex17, hn, lnCn, det
check(sl17 >= -1e-6 and det17 > 0,
      f"defaults, absolute hue: hue slope >= 1 - wgt on 3601 hues x 201 chromas and 2D (ln C, h) "
      f"Jacobian det > 0 at L 0.3 / 0.6 / 0.9: " + "; ".join(rows17))

check(not NONFINITE, f"every swept array is finite (no NaN / inf hidden by a min / max reduction)"
      + ("" if not NONFINITE else f": non-finite in {sorted(set(NONFINITE))}"))

print("\n" + ("ALL OK" if not FAIL else f"{len(FAIL)} FAILURE(S)"))
sys.exit(1 if FAIL else 0)
