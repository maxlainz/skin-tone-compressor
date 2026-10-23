#!/usr/bin/env python3
"""numpy float64 model of the Skin Tone Compressor DCTL (dctl/SkinToneCompressor.dctl).

Used by tools/verify.py (numerical checks). Import only: nothing runs and
nothing is checked at import time.

Contents:
  - the six working-space curves (encode/decode) and CURVES / WS_MAT /
    WS_ORDER (Working Space combo index -> curve and matrix set);
  - parse_matrices(): the `// MAT NAME` blocks of the DCTL text;
  - to_lab / from_lab: linear RGB(ws) <-> Oklab through the DCTL's own
    parsed matrices;
  - AP0_AP1 and CC (ColorChecker dark/light skin, AP0);
  - softplus (overflow-safe form of the DCTL), width_sigma() (the Zone Hue
    Edge width blend), pixel_core() (the arithmetic of transform() up to the
    Mix blend, plus the zone weight a = wField * kH), pixel() (RGB, alpha,
    Output Zone Alpha and Show Shift), parse_ui_defaults() and model(): one
    call from DCTL text + parameters to (output codes, alpha).

Parameters use the DCTL's own UI variable names (PARAMS); an unknown key
raises. This is a hand copy of the DCTL: change a formula in the DCTL and here
in the same commit (tools/verify.py checks the DCTL text against canonical
strings).
"""
import re

import numpy as np

# =====================================================================
# Log curves (closed forms from the official specs, quoted in the DCTL)
# =====================================================================
TWO_M16, TWO_M15 = 2.0 ** -16, 2.0 ** -15
CC_FLOOR = (np.log2(TWO_M16) + 9.72) / 17.52
CC_LOWCUT = (9.72 - 15) / 17.52
CC_HICUT = (np.log2(65504) + 9.72) / 17.52
DI_A, DI_B, DI_C, DI_M = 0.0075, 7.0, 0.07329248, 10.44426855
DI_LIN_CUT, DI_LOG_CUT = 0.00262409, 0.02740668
LC4_B, LC4_C, LC4_A = (1023 - 95) / 1023, 95 / 1023, (2 ** 18 - 16) / 117.45
LC4_S = 7 * np.log(2) * 2 ** (7 - 14 * LC4_C / LC4_B) / (LC4_A * LC4_B)
LC4_T = (2 ** (14 * (-LC4_C / LC4_B) + 6) - 64) / LC4_A


def _pos(x):
    return np.where(x > 0, x, 1.0)            # keep the unused log branch finite


def cct_enc(x):
    return np.where(x <= 0.0078125, 10.5402377416545 * x + 0.0729055341958355, (np.log2(_pos(x)) + 9.72) / 17.52)


def cct_dec(x):
    return np.where(x > 0.155251141552511, 2.0 ** (x * 17.52 - 9.72), (x - 0.0729055341958355) / 10.5402377416545)


def cc_enc(x):
    lo = (np.log2(TWO_M16 + np.maximum(x, 0) * 0.5) + 9.72) / 17.52
    hi = (np.log2(_pos(x)) + 9.72) / 17.52
    return np.where(x <= 0, CC_FLOOR, np.where(x < TWO_M15, lo, hi))


def cc_dec(x):
    lo = (2.0 ** (x * 17.52 - 9.72) - TWO_M16) * 2
    mid = 2.0 ** (np.minimum(x, CC_HICUT) * 17.52 - 9.72)
    return np.where(x <= CC_LOWCUT, lo, np.where(x < CC_HICUT, mid, 65504.0))


def di_enc(x):
    return np.where(x > DI_LIN_CUT, (np.log2(_pos(x + DI_A)) + DI_B) * DI_C, x * DI_M)


def di_dec(x):
    return np.where(x > DI_LOG_CUT, 2.0 ** (x / DI_C - DI_B) - DI_A, x / DI_M)


def lc4_enc(x):
    return np.where(x >= LC4_T, (np.log2(_pos(LC4_A * x + 64)) - 6) / 14 * LC4_B + LC4_C, (x - LC4_T) / LC4_S)


def lc4_dec(x):
    return np.where(x >= 0, (2.0 ** (14 * (x - LC4_C) / LC4_B + 6) - 64) / LC4_A, x * LC4_S + LC4_T)


# Display-referred curves, mirrored about 0 (odd, strictly increasing on R).
# Rec.709 Gamma 2.4: ITU-R BT.1886 EOTF with black 0. sRGB: IEC 61966-2-1.
SRGB_DEC_CUT, SRGB_ENC_CUT = 0.04045, 0.0031308


def r709_enc(x):
    return np.copysign(np.abs(x) ** (1 / 2.4), x)


def r709_dec(x):
    return np.copysign(np.abs(x) ** 2.4, x)


def srgb_enc(x):
    ax = np.abs(x)
    return np.where(ax <= SRGB_ENC_CUT, 12.92 * x, np.copysign(1.055 * ax ** (1 / 2.4) - 0.055, x))


def srgb_dec(x):
    ax = np.abs(x)
    return np.where(ax <= SRGB_DEC_CUT, x / 12.92, np.copysign(((ax + 0.055) / 1.055) ** 2.4, x))


CURVES = {   # name: (encode, decode, valid linear domain)
    "ACEScct": (cct_enc, cct_dec, (-0.0069, 65504.0)),
    "ACEScc": (cc_enc, cc_dec, (1e-12, 65504.0)),
    "DWG": (di_enc, di_dec, (-0.1, 100.0)),
    "LogC4": (lc4_enc, lc4_dec, (LC4_T, 2.0 ** 18)),
    "Rec709": (r709_enc, r709_dec, (-1.0, 10.0)),
    "sRGB": (srgb_enc, srgb_dec, (-1.0, 10.0)),
}
WS_MAT = {"ACEScct": "AP1", "ACEScc": "AP1", "DWG": "DWG", "LogC4": "AWG4", "Rec709": "REC709", "sRGB": "REC709"}
WS_ORDER = ["ACEScct", "ACEScc", "DWG", "LogC4", "Rec709", "sRGB"]   # Working Space combo index 0..5

# ColorChecker skin patches in ACES2065-1 (AP0) and the AP0 -> AP1 matrix.
AP0_AP1 = np.array([[1.4514393161, -0.2365107469, -0.2149285693],
                    [-0.0765537734, 1.1762296998, -0.0996759264],
                    [0.0083161484, -0.0060324498, 0.9977163014]])
CC = {"dark skin": [0.11877, 0.08709, 0.05895], "light skin": [0.40002, 0.31916, 0.23737]}

# =====================================================================
# Matrix parser
# =====================================================================
MAT_ROW = re.compile(r"^\s*([+-]?)(\d+\.\d+)f \* c\.x\s*([+-])(\d+\.\d+)f \* c\.y\s*([+-])(\d+\.\d+)f \* c\.z\s*[,)]*;?\s*$")


def parse_matrices(text, fname):
    """Parse every `// MAT NAME` block of the DCTL text into {NAME: 3x3}.

    Each marker is followed by exactly 3 rows, each fullmatching
    `[+-]C * c.x [+-]C * c.y [+-]C * c.z` (C = digits.digits f) plus an optional
    `,` / `)` / `;` tail: a stray additive term, a swapped column or a missing
    sign fails. Problems are returned as messages (clean FAIL, no traceback).
    """
    lines = text.splitlines()
    mats, errors = {}, []
    for i, line in enumerate(lines):
        mk = re.match(r"\s*//\s*MAT\s+(\w+)\s*$", line)
        if not mk:
            continue
        name = mk.group(1)
        if name in mats:
            errors.append(f"{fname}: MAT {name} appears twice")
            continue
        M = []
        for row_line in lines[i + 1:i + 4]:
            m = MAT_ROW.match(row_line)
            if not m:
                errors.append(f"{fname}: MAT {name}: row does not match `C * c.x C * c.y C * c.z`: {row_line.strip()}")
                break
            g = m.groups()
            M.append([(-1.0 if g[k] == "-" else 1.0) * float(g[k + 1]) for k in (0, 2, 4)])
        if len(M) == 3:
            mats[name] = np.array(M)
    return mats, errors


# =====================================================================
# RGB(ws) linear <-> Oklab with the DCTL's own matrices
# =====================================================================


def to_lab(rgb, mat, mats):
    """Linear RGB of matrix set `mat` (AP1, DWG, AWG4, REC709) -> Oklab, rows of rgb are pixels."""
    return (mats["OKLAB_M2"] @ np.cbrt(mats["OKLAB_M1"] @ mats[f"{mat}_TO_XYZ"] @ rgb.T)).T


def from_lab(lab, mat, mats, m2_inv=None):
    m2i = mats["OKLAB_M2_INV"] if m2_inv is None else m2_inv
    return (mats[f"XYZ_TO_{mat}"] @ mats["OKLAB_M1_INV"] @ ((m2i @ lab.T) ** 3)).T


# =====================================================================
# The pixel transform
# =====================================================================
PARAMS = ("workingSpace", "targetHue", "targetHueTilt", "targetChroma", "targetChromaTilt", "tiltPivot",
          "zoneHueYellow", "zoneHueRed", "zoneHueEdge", "zoneChromaMin", "zoneChromaMax", "zoneLumaWindow",
          "zoneLumaMin", "zoneLumaMax", "hueStrength", "chromaStrength", "chromaLift", "chromaTolerance",
          "lipsProtect", "lipsChromaMin", "mix", "outputAlpha", "showShift")   # DEFINE_UI_PARAMS order
LIPS_FLOOR = 0.9      # the red-range shrink removes at most 90 % of Zone Hue Range Red
LIFT_EPS = 0.05       # Chroma Lift: lc = eps ln cosh(th / eps), a smooth |th|
EDGE_GAIN = 16.0      # s = 16 * zoneHueEdge


def softplus(x, k):
    return np.maximum(x, 0.0) + k * np.log1p(np.exp(-np.abs(x) / k))


def width_sigma(d, s):
    """Width-blend weight (1 towards yellow at d = +90 deg, 0 towards red at -90 deg).

    s = 0: sig0 = 0.5 (1 + sin d), the smooth sine blend. s > 0: sig0 + m (sigS - sig0),
    sigS = 0.5 (1 + tanh(s sin d) / tanh(s)) (sharp switch at sin d = 0), m = 0.5 (1 + cos d)
    (window: 1 at the target, 0 at the anti-target, so the opposite hue keeps the smooth
    blend). s is a UI parameter (s = EDGE_GAIN * zoneHueEdge)."""
    if s > 0:
        return (0.5 * (1 + np.sin(d)) + 0.5 * (1 + np.cos(d)) * (0.5 * (1 + np.tanh(s * np.sin(d)) / np.tanh(s))
                                                               - 0.5 * (1 + np.sin(d))))
    return 0.5 * (1 + np.sin(d))


def pixel_core(x, p, dec, to_lab):
    """transform() arithmetic up to the Mix blend, in the DCTL's order:
      wField   wKnee * wCeil * wL (zone chroma knee / ceiling, Zone Luma Window)
      cL       1 - 1/(1 + (C / max(lipsChromaMin, 0.001))^2)
      wR       clamp(zoneHueRed, 1, 180) * (1 - 0.9 * lipsProtect * cL) deg
      w        wR + (wY - wR) * width_sigma(d, 16 * zoneHueEdge): one kernel for kH and the hue remap
      g        0.5 (1 + r) th + 0.5 (1 - r) lc, th = tanh(f), r = chromaLift * 0.01; Cn = C exp(-wC g)
    p holds every PARAMS key except outputAlpha / showShift / workingSpace (optional). With dec
    and to_lab the identity, x is an Oklab array (verify.py sweeps (L, C, h) directly). Returns
    (lin, lab, labn, a, ex), a = wField * kH (the zone weight), ex = dict(h, hn, wC, f, g, wL,
    cL, wR, wgt, Lc, kH, w).
    """
    unknown = set(p) - set(PARAMS)
    if unknown:
        raise KeyError(f"unknown parameter(s) {sorted(unknown)}")
    lin = dec(x)
    lab = to_lab(lin)
    C = np.hypot(lab[:, 1], lab[:, 2])
    h = np.where(C > 0, np.arctan2(lab[:, 2], lab[:, 1]), 0.0)
    k2 = p["zoneChromaMin"] ** 2
    wKnee = C * C / (C * C + k2) if k2 > 0 else np.ones_like(C)
    wCeil = 1.0 / (1.0 + (C / p["zoneChromaMax"]) ** 4)
    Lc = lab[:, 0] - softplus(lab[:, 0] - 1.2, 0.05) + softplus(-lab[:, 0], 0.05)
    if int(p["zoneLumaWindow"]):
        m8 = p["zoneLumaMin"] ** 8
        wLKnee = Lc ** 8 / (Lc ** 8 + m8) if m8 > 0 else np.ones_like(Lc)
        wL = wLKnee * (1.0 / (1.0 + (Lc / max(p["zoneLumaMax"], 0.01)) ** 8))
    else:
        wL = 1.0
    cL = 1.0 - 1.0 / (1.0 + (C / max(p["lipsChromaMin"], 0.001)) ** 2)
    wField = wKnee * wCeil * wL
    wgt = np.minimum(p["hueStrength"] * wField, 0.99)
    target = np.radians(p["targetHue"] + p["targetHueTilt"] * (Lc - p["tiltPivot"]))
    wY = np.radians(min(max(p["zoneHueYellow"], 1.0), 180.0))
    wR = np.radians(min(max(p["zoneHueRed"], 1.0), 180.0) * (1.0 - LIPS_FLOOR * p["lipsProtect"] * cL))
    d = h - target
    d = d - 2 * np.pi * np.round(d / (2 * np.pi))
    s = EDGE_GAIN * p["zoneHueEdge"]
    w = wR + (wY - wR) * width_sigma(d, s)
    kH = np.exp((np.cos(d) - 1) / (w * w))
    wC = np.minimum(p["chromaStrength"] * wField * kH, 0.99)
    hn = target + d - wgt * np.sin(d) * np.exp((np.cos(d) - 1) / (w * w))
    u = np.log(np.maximum(C, 1e-12) / p["targetChroma"]) - (p["targetChromaTilt"] * 0.01) * (Lc - p["tiltPivot"])
    delta = np.log(1 + p["chromaTolerance"] * 0.01)
    f = u - delta * np.tanh(np.clip(u / delta, -20, 20)) if delta > 1e-4 else u
    th = np.tanh(f)
    r = p["chromaLift"] * 0.01
    xl = np.abs(th) / LIFT_EPS
    lc = LIFT_EPS * (xl + np.log(1.0 + np.exp(-2.0 * xl)) - np.log(2.0))
    g = 0.5 * (1.0 + r) * th + 0.5 * (1.0 - r) * lc
    Cn = C * np.exp(-wC * g)
    labn = np.stack([lab[:, 0], Cn * np.cos(hn), Cn * np.sin(hn)], axis=1)
    labn = lab + (labn - lab) * p["mix"]
    return lin, lab, labn, wField * kH, dict(h=h, hn=hn, wC=wC, f=f, g=g, wL=wL, cL=cL, wR=wR, wgt=wgt, Lc=Lc,
                                              kH=kH, w=w)


def pixel(x, p, dec, enc, to_lab, from_lab, alpha_in=None):
    """numpy float64 copy of transform(): RGB and alpha. Returns (out, alpha, info),
    info = dict(outl, lin, lab, labn, a, shift, ex). outputAlpha defaults to 1 and
    showShift to 0 when absent; alpha_in is the input alpha p_A (default 1):
      alpha    = a * alpha_in if outputAlpha else alpha_in
      outl     = lin + (F(labn) - F(lab))          (exact bypass at Mix 0)
      dh       = wrap(hn - h);  dlnC = -wC * g
      shift    = (0.5 + dh * 57.29577951 / 60 * mix, 0.5 + dlnC * mix, 0.5)
      out      = shift if showShift else enc(outl) (raw codes, no encode)
    """
    lin, lab, labn, a, ex = pixel_core(x, p, dec, to_lab)
    show = int(p.get("showShift", 0))
    out_alpha = int(p.get("outputAlpha", 1))
    if alpha_in is None:
        alpha_in = np.ones(len(lab))
    alpha = a * np.asarray(alpha_in) if out_alpha else np.asarray(alpha_in)
    outl = lin + (from_lab(labn) - from_lab(lab))
    dh = ex["hn"] - ex["h"]
    dh = dh - 2 * np.pi * np.round(dh / (2 * np.pi))
    dlnC = -ex["wC"] * ex["g"]
    mix = p["mix"]
    shift = np.stack([0.5 + dh * 57.29577951 / 60.0 * mix, 0.5 + dlnC * mix, np.full_like(dh, 0.5)], axis=1)
    out = shift if show else enc(outl)
    return out, alpha, dict(outl=outl, lin=lin, lab=lab, labn=labn, a=a, shift=shift, ex=ex)


# =====================================================================
# DCTL text -> parameters -> model
# =====================================================================
UI_PARAM = re.compile(r"^\s*DEFINE_UI_PARAMS\(\s*(\w+)\s*,[^,]*,\s*(DCTLUI_\w+)\s*,\s*([+-]?\d+(?:\.\d*)?)", re.M)


def parse_ui_defaults(text):
    """{var: default} from every DEFINE_UI_PARAMS line of a DCTL text.

    Sliders give floats; DCTLUI_CHECK_BOX and DCTLUI_COMBO_BOX give ints (the
    combo default is its enum index).
    """
    out = {}
    for var, kind, val in UI_PARAM.findall(text):
        out[var] = int(float(val)) if kind in ("DCTLUI_CHECK_BOX", "DCTLUI_COMBO_BOX") else float(val)
    return out


def model(codes, text, params=None, fname="SkinToneCompressor.dctl", alpha=None):
    """(float64 output codes, alpha) of the DCTL text for input codes (N, 3) and input
    alpha (N,) (default 1). params defaults to the DCTL's own DEFINE_UI_PARAMS defaults;
    its workingSpace (combo index) picks the curve and matrix set."""
    mats, errors = parse_matrices(text, fname)
    if errors:
        raise ValueError("; ".join(errors))
    p = parse_ui_defaults(text) if params is None else params
    ws = WS_ORDER[int(p.get("workingSpace", 0))]
    enc, dec, _ = CURVES[ws]
    mat = WS_MAT[ws]
    out, a_out, _ = pixel(codes, p, dec, enc, lambda r: to_lab(r, mat, mats), lambda l: from_lab(l, mat, mats), alpha)
    return out, a_out
