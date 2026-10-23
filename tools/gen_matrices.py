#!/usr/bin/env python3
"""Generate the per-working-space matrices embedded in the DCTL (dctl/SkinToneCompressor.dctl).

    python3 tools/gen_matrices.py          # prints the two DCTL blocks to stdout

The output is pasteable verbatim: block 1 is the per-space matrix functions
(mat_ap1_to_xyz .. mat_xyz_to_rec709), block 2 the Oklab matrix functions
(mat_oklab_m1 .. mat_oklab_m1_inv). tools/verify.py checks that both blocks
appear verbatim in the DCTL.

The DCTL keeps three explicit layers between the working space and Oklab:
  (a) log <-> linear      per space, in the DCTL (no matrices)
  (b) RGB <-> XYZ         normalised primary matrix (NPM) from the space's
                          primaries and white, SMPTE RP 177 method
  (c) white -> D65        Bradford chromatic adaptation to Oklab's D65 white,
                          then Ottosson's canonical M1 / M2, untouched
Layers (b) and (c-CAT) are folded here into ONE matrix per space,
RGB -> XYZ(D65), so the DCTL does  RGB -> XYZ_D65 -> M1 -> cbrt -> M2.
For D65 spaces the CAT is the identity and the folded matrix equals the
official RGB -> XYZ matrix of the whitepaper (checked below).

Sources (all constants are quoted from these):
  AP1 primaries + ACES white   docs.acescentral.com/encodings/acescg/ (Table 1);
                               white x=0.32168 y=0.33767 (ACES white, not CIE D60)
  DWG primaries + matrices     BMD, "DaVinci Wide Gamut / DaVinci Intermediate",
                               rev 1.1, 2021-07-31 (documents.blackmagicdesign.com)
  AWG4 primaries + matrix      ARRI, "LogC4 Logarithmic Color Space Specification",
                               Eq. 5a (www.arri.com, 2022-09, rev 2025-01-23)
  Bradford                     Lam 1985 via brucelindbloom.com/Eqn_ChromAdapt.html
  Oklab M1, M2, M2^-1          bottosson.github.io/posts/oklab/ (2021-01-25 update)
  Rec.709 / sRGB primaries     ITU-R BT.709-6 (Part 2, item 1.3) = IEC 61966-2-1:1999
                               (sRGB); white D65. The IEC RGB -> XYZ matrix is printed
                               to 4 digits only, so it is checked to 1e-4.
M1^-1 and the XYZ -> RGB matrices are not published numerically: they are the
float64 inverses of the forward matrices, rounded to 10 significant digits.
`tools/verify.py` re-derives everything here and compares it with the DCTL.
"""
import numpy as np

DIGITS = 10


def xy2XYZ(x, y):
    return np.array([x / y, 1.0, (1.0 - x - y) / y])


def npm(prim, white):
    """SMPTE RP 177 normalised primary matrix: RGB -> XYZ with white -> Y=1."""
    P = np.array([xy2XYZ(*p) for p in prim]).T        # columns: XYZ of R, G, B
    S = np.linalg.solve(P, xy2XYZ(*white))
    return P * S


BRADFORD = np.array([[0.8951, 0.2664, -0.1614],
                     [-0.7502, 1.7135, 0.0367],
                     [0.0389, -0.0685, 1.0296]])
D65 = (0.3127, 0.3290)


def bradford(src_xy, dst_xy):
    if src_xy == dst_xy:
        return np.eye(3)
    ws, wd = xy2XYZ(*src_xy), xy2XYZ(*dst_xy)
    return np.linalg.inv(BRADFORD) @ np.diag((BRADFORD @ wd) / (BRADFORD @ ws)) @ BRADFORD


# name, enum, primaries (R, G, B) xy, white xy
SPACES = [
    ("ACES AP1 (ACEScct / ACEScc)", "AP1",
     [(0.713, 0.293), (0.165, 0.830), (0.128, 0.044)], (0.32168, 0.33767)),
    ("DaVinci Wide Gamut", "DWG",
     [(0.8000, 0.3130), (0.1682, 0.9877), (0.0790, -0.1155)], D65),
    ("ARRI Wide Gamut 4", "AWG4",
     [(0.7347, 0.2653), (0.1424, 0.8576), (0.0991, -0.0308)], D65),
    ("Rec.709 / sRGB", "REC709",                      # shared by the Rec.709 Gamma 2.4 and sRGB curves
     [(0.64, 0.33), (0.30, 0.60), (0.15, 0.06)], D65),
]

# Official matrices as printed, used only as a self-check of the derivation
OFFICIAL = {
    "DWG": np.array([[0.70062239, 0.14877482, 0.10105872],
                     [0.27411851, 0.87363190, -0.14775041],
                     [-0.09896291, -0.13789533, 1.32591599]]),
    "AWG4": np.array([[0.704858320407232064, 0.129760295170463003, 0.115837311473976537],
                      [0.254524176404027025, 0.781477732712002049, -0.036001909116029039],
                      [0.0, 0.0, 1.089057750759878429]]),
    # IEC 61966-2-1:1999 Eq. (F.7) / ITU-R BT.709: published rounded to 4 digits
    "REC709": np.array([[0.4124, 0.3576, 0.1805],
                        [0.2126, 0.7152, 0.0722],
                        [0.0193, 0.1192, 0.9505]]),
}
# Tolerance of the self-check against OFFICIAL (the default fits the 8+ digit
# whitepaper matrices; the IEC sRGB matrix is printed to 4 digits).
OFFICIAL_TOL = {"REC709": 1e-4}

M1 = np.array([[0.8189330101, 0.3618667424, -0.1288597137],
               [0.0329845436, 0.9293118715, 0.0361456387],
               [0.0482003018, 0.2643662691, 0.6338517070]])
M2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
               [1.9779984951, -2.4285922050, 0.4505937099],
               [0.0259040371, 0.7827717662, -0.8086757660]])
M2_INV_PUBLISHED = np.array([[1.0, 0.3963377774, 0.2158037573],
                             [1.0, -0.1055613458, -0.0638541728],
                             [1.0, -0.0894841775, -1.2914855480]])


def rgb_to_xyz_d65(prim, white):
    return bradford(white, D65) @ npm(prim, white)


def fmt(v):
    """10 significant digits, positional, as a C float literal (0 -> 0.0f)."""
    s = np.format_float_positional(float(f"{v:.{DIGITS}g}"), trim="-", unique=True)
    return (s if "." in s else s + ".0") + "f"


def fmt_published(v):
    """Published Oklab coefficients as printed by Ottosson: 10 decimals (exact integers as 1.0f)."""
    return ("%.1f" % v if v == int(v) else "%.10f" % v) + "f"


def rows(M, var, f=fmt):
    """Three DCTL rows `coef * var.x + coef * var.y + coef * var.z`, the last two ending `,` and `);`."""
    out = []
    for i in range(3):
        terms = [f"{'-' if M[i, j] < 0 else '+'}{f(abs(M[i, j]))} * {var}.{'xyz'[j]}" for j in range(3)]
        out.append("    " + " ".join(terms).lstrip("+") + (");" if i == 2 else ","))
    return "\n".join(out)


def mat_func(fname, mname, M, f=fmt):
    return (f"__DEVICE__ float3 {fname}(float3 c) {{\n    return make_float3(\n// MAT {mname}\n"
            f"{rows(M, 'c', f)}\n}}")


def dctl_blocks():
    """(block 1: per-space RGB <-> XYZ(D65) functions, block 2: Oklab matrix functions), as in the DCTL."""
    b1 = []
    for name, enum, prim, white in SPACES:
        M = rgb_to_xyz_d65(prim, white)
        if enum in OFFICIAL:
            assert np.abs(M - OFFICIAL[enum]).max() <= OFFICIAL_TOL.get(enum, 6e-9), enum
        cat = "Bradford %s -> D65" % (white,) if white != D65 else "no CAT, native D65"
        b1 += [f"// {name}: RGB -> XYZ(D65) [{cat}] and inverse",
               mat_func(f"mat_{enum.lower()}_to_xyz", f"{enum}_TO_XYZ", M),
               mat_func(f"mat_xyz_to_{enum.lower()}", f"XYZ_TO_{enum}", np.linalg.inv(M))]
    b2 = [mat_func("mat_oklab_m1", "OKLAB_M1", M1, fmt_published),
          mat_func("mat_oklab_m2", "OKLAB_M2", M2, fmt_published),
          mat_func("mat_oklab_m2_inv", "OKLAB_M2_INV", M2_INV_PUBLISHED, fmt_published),
          "// Oklab M1^-1 (LMS -> XYZ D65), float64 inverse of the published M1",
          mat_func("mat_oklab_m1_inv", "OKLAB_M1_INV", np.linalg.inv(M1))]
    return "\n".join(b1), "\n".join(b2)


if __name__ == "__main__":
    b1, b2 = dctl_blocks()
    print(b1 + "\n\n" + b2)
