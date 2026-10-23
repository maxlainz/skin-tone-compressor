# Skin Tone Compressor

An elastic skin tone compressor for DaVinci Resolve, written as a single DCTL file.

It pulls the hue and chroma of colors near skin toward a target skin line with a smooth, periodic, **monotonic** remap over the whole color cube. There are no masks, keys or qualifiers: neighboring colors move together with the skin, so a hue ramp stays a ramp (no inversions, no steps, no banding). Work happens in Oklab, and Oklab **L (lightness) is never modified**: only hue and chroma move. A soft "zone weight" is also written to the alpha channel (see [Install](#install) for the status of that output).

## Contents

- [Install](#install)
- [Working spaces](#working-spaces)
- [Quick start](#quick-start)
- [Parameters](#parameters)
- [How it works](#how-it-works)
- [Design guarantees](#design-guarantees)
- [Limitations](#limitations)
- [Default skin references](#default-skin-references)
- [Glossary](#glossary)
- [Development](#development)
- [Contributing](#contributing)
- [License](#license)

## Install

DCTL effects require **DaVinci Resolve Studio**. The ResolveFX DCTL plugin with alpha support needs Resolve 19.1 or later.

1. Download `SkinToneCompressor.dctl` from the [latest GitHub Release](https://github.com/maxlainz/skin-tone-compressor/releases/latest).
2. Copy it into Resolve's LUT folder (or a subfolder of it). In Resolve, *Project Settings > Color Management > Lookup Table > Open LUT Folder* opens it. Default locations:

   | OS | Path |
   |---|---|
   | macOS | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT` |
   | Windows | `C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\LUT` |
   | Linux | `/opt/resolve/LUT` |

3. In Resolve, press *Update Lists* in the same Project Settings page, or restart Resolve.
4. Use the **ResolveFX DCTL** plugin. On the Color page, add a node and open *OpenFX > ResolveFX Color > DCTL* (on the Edit page: *Effects Library > OpenFX > Filters > ResolveFX Color > DCTL*), then pick `SkinToneCompressor` in the plugin's DCTL list.

**About the alpha output.** The file is a "Transform DCTL with alpha" (it declares `DEFINE_DCTL_ALPHA_MODE_STRAIGHT` and `transform()` receives and returns RGBA). Blackmagic documents this for the ResolveFX DCTL plugin. The alpha output carries the **zone weight**, from 0 to 1, in straight alpha (RGB is not premultiplied). Viewing or using it as a key in Resolve (for example with *Use OFX Alpha* and Highlight) has not been fully tested yet; feedback is welcome.

## Working spaces

Set *Working Space* to the space in which the node receives its pixels. Input and output are always in the same space.

| Working Space | Use it for |
|---|---|
| ACEScct (default) | ACES pipelines, grading between IDT and ODT. Preferred over ACEScc in ACES |
| ACEScc | ACES pipelines using ACEScc |
| DaVinci Intermediate | DaVinci Wide Gamut / DaVinci Intermediate timelines (RCM) |
| ARRI LogC4 | ARRI LogC4 / AWG4 material without a transform |
| Rec.709 Gamma 2.4 | Timelines without color management, clips already in Rec.709 (display-referred) |
| sRGB | Same, with the sRGB transfer function |

If the timeline is in another space, wrap the node with a Color Space Transform. A wrong space breaks nothing visibly (there are no masks) but moves skin hue and chroma and makes the defaults invalid. The node cannot detect which space it receives. Rec.709 and sRGB are display-referred: codes above 1 and negative codes are processed without clipping.

All color parameters are absolute Oklab values (XYZ D65), identical whichever working space is chosen.

## Quick start

1. **See the zone.** The alpha output carries the zone weight; to view it, try right-click on the node > *Use OFX Alpha* together with Resolve's **Highlight** (Shift+H). This view has not been fully tested yet; feedback is welcome. If orange clothes or wood enter the zone, lower *Zone Chroma Max*. If gray noise or a nearly neutral background enters, raise *Zone Chroma Min*. If the zone reaches too far toward yellow or red, lower *Zone Hue Range* on that side. To see **how much** each pixel moves, turn on *Show Shift*: mid-gray means untouched; reddish/cyan means hue rotated; green/magenta means chroma changed.
2. **Set the skin line.** Turn the diagnostic views off. Set *Hue Strength* 0.99 and *Zone Hue Range* Yellow and Red to 20 (diagnostic only, to see what the zone catches), look at a face with shadow and light on the vectorscope, and adjust *Target Hue Tilt vs Luma* until the skin line is straight.
3. **Back to a gentle setting.** *Hue Strength* around 0.5 and ranges around 45. If skin drifts toward yellow/green (fluorescent light) and you do not want to touch the reds of the lips, raise *Zone Hue Range Yellow* and leave *Red*. Set *Target Chroma* to the real median chroma of the shot in the midtones (vectorscope or picker); *Chroma Tolerance* forgives about 20-30 %. If face highlights are too saturated, lower *Target Chroma Tilt vs Luma*; if shadows are gray, raise it.
4. **Chroma.** Raise *Chroma Strength* to taste. If shadows gain chroma noise or dull skin gets saturated, lower *Chroma Lift* (0 = desaturate only).
5. **Lips and blush.** If lips or cheeks drift toward orange or lose saturation, raise *Lips Protect* and tune *Lips Chroma Min* while watching Highlight: the lips should leave the key without the neighboring skin disappearing. If the lip is still inside the key at Protect 1, raise *Zone Hue Edge* to about 0.5. If it is still inside, the lip has the same hue as the skin; only lowering *Zone Chroma Max* removes it (at the cost of saturated skin).
6. **Dark or bright look-alikes.** If dark wood, sand or hair enter the key, enable *Zone Luma Window* and raise *Zone Luma Min*; for specular highlights, lower *Zone Luma Max*. If the face is exposed far from Oklab L 0.6, set *Tilt Pivot Luma* to its lightness before touching the tilts.

Always test with a continuous hue ramp as well as faces: there must be no steps.

## Parameters

Controls are grouped in four families, in panel order: **Target** (where skin goes), **Zone** (which pixels are affected, always with soft edges), **Strength** (how hard it pulls) and **Lips** (what to leave out). *Working Space* is at the top; *Mix*, *Output Zone Alpha* and *Show Shift* at the bottom.

| Control | Default | Range | What it does |
|---|---|---|---|
| Working Space | ACEScct | ACEScct, ACEScc, DaVinci Intermediate, ARRI LogC4, Rec.709 Gamma 2.4, sRGB | Input and output space. Only changes the conversion to and from Oklab. |
| **Target Hue deg** | 47 | 0-360 | Oklab hue that skin is pulled toward. See [Default skin references](#default-skin-references). |
| **Target Hue Tilt vs Luma deg** | 12 | -60 to 60 | Rotation of the target hue per unit of Oklab L around the pivot: shadows toward red, highlights toward yellow, like real skin. |
| **Target Chroma** | 0.06 | 0.01-0.2 | Oklab chroma that skin is pulled toward, at L = pivot. |
| **Target Chroma Tilt vs Luma pct** | 60 | -150 to 150 | Percent change of the target chroma per unit of L (exponential, around the pivot). 60 follows the ColorChecker skin patches: lighter skin has more chroma. 0 = flat chroma target. |
| **Tilt Pivot Luma** | 0.6 | 0.2-1.0 | Oklab L around which both tilts rotate: at this L the target is exactly *Target Hue* / *Target Chroma*. Set it to the lightness of the face (0.45-0.7). |
| **Zone Hue Range Yellow deg** | 45 | 5-180 | How far the zone reaches toward yellow (at +90 degrees from the target). Below about 20 degrees hues start to bunch up. |
| **Zone Hue Range Red deg** | 45 | 5-180 | How far the zone reaches toward red/magenta (at -90 degrees). At the target and at the opposite hue the average of the two applies. More range = more pull from that side. |
| **Zone Hue Edge** | 0 | 0-1 | How abrupt the switch from the Yellow range to the Red range is around the target. At 0 the blend is sinusoidal and very gradual (15 degrees from the target the average of both widths still dominates). At 0.5, 5 degrees from the target the width of that side already dominates almost fully. This is what lets *Lips Protect* act on lips 10-25 degrees from the skin hue. Above 0.5 it mostly costs skin. Has no effect when both ranges are equal and *Lips Protect* is 0. |
| **Zone Chroma Min** | 0.025 | 0.001-0.1 | Chroma below which the zone fades out (neutrals, gray noise). Cannot be 0: at 0 the field would be discontinuous on the neutral axis. |
| **Zone Chroma Max** | 0.35 | 0.05-0.5 | Chroma above which the zone fades out (saturated oranges: clothes, wood). 0.35 is effectively off. |
| **Zone Luma Window** | off | checkbox | Enables the lightness window below. |
| **Zone Luma Min / Max** | 0.10 / 1.10 | 0-0.8 / 0.3-1.5 | With the window on, the zone fades out softly below Min and above Max (Oklab L; each edge is 0.5 exactly at its value, order-8 falloff). Excludes dark wood, sand, dark hair, or speculars. It cuts hue, chroma and alpha together. Min above Max silently turns the effect off; since the internal L is clamped to 1.2, a Max between 1.2 and 1.5 never opens fully. |
| **Hue Strength** | 0.5 | 0-0.99 | How strongly hue is pulled toward the target. |
| **Chroma Strength** | 0.3 | 0-0.99 | How strongly chroma is pulled toward the target when lowering it (see *Chroma Lift* for raising). |
| **Chroma Lift pct** | 100 | 0-100 | Percent of *Chroma Strength* applied when chroma is **below** the target and would be raised. 100 = symmetric. 0 = practically desaturate only (the residual lift is at most 1.7 % of the pull; desaturation keeps about 94 %). Avoids raising chroma noise in shadows and saturating dull skin. |
| **Chroma Tolerance pct** | 30 | 0-100 | Band of +/- percent around the target chroma that is left untouched; only the tails converge. |
| **Lips Protect** | 0 | 0-1 | Lip and blush protection: narrows *Zone Hue Range Red* for colors with chroma above *Lips Chroma Min* (by up to 90 % at Protect 1). Those pixels leave the zone: less hue rotation, less chroma change, less alpha, with no separate mask or kernel. Because widths are blended periodically, the narrowing leaks slightly to the yellow side, and with *Zone Hue Edge* 0 it barely acts within 25 degrees of the skin hue; use *Zone Hue Edge* about 0.5. |
| **Lips Chroma Min** | 0.10 | 0.03-0.4 | Chroma at which *Lips Protect* reaches half effect. Lips and cheeks typically have more chroma than skin (roughly 0.10-0.2 versus 0.05-0.07). It is an absolute chroma: with a high *Target Chroma Tilt* and a low pivot the target in the highlights can exceed it and light skin may lose its red side; raise it then. |
| Mix | 1.0 | 0-1 | Blend with the input (done in Oklab, so L stays exact at any Mix). |
| Output Zone Alpha | on | checkbox | Writes the **zone weight** to alpha: `a = Zone Chroma field x hue kernel` in [0, 1]. Independent of the Strengths and of *Mix*: it says what is skin, not how much it moves. Output alpha = weight x input alpha, so an upstream key or window is respected (with input alpha 1 it is the weight itself). Off = input alpha passes through unchanged. Independent of *Show Shift*. |
| Show Shift | off | checkbox | False-color diagnostic of **how much each pixel moves**. Mid-gray = unchanged. **R**: hue rotation, 0.5 + rotation/60 degrees (R > 0.5 = rotates toward yellow, R < 0.5 = toward red). **G**: chroma change, 0.5 + ln(C'/C) (G < 0.5 = desaturated, G > 0.5 = saturated). B = 0.5. Includes *Mix*. Raw values, not log-encoded and not clipped: with strong settings they leave 0..1 (read them on scopes). |

## How it works

### Pipeline

```
log(space) -> linear RGB of the space                (a) per-space transfer function
   -> XYZ(D65)                                       (b) primaries -> XYZ and (c) Bradford to D65, folded into one 3x3 per space
   -> LMS = M1 * XYZ -> cube root -> Lab = M2 * LMS' (c) canonical Oklab matrices, untouched
   -> (L, C, h)
   -> h' = remap_hue(h)        (the red range narrows with chroma if Lips Protect > 0; the yellow/red blend sharpens with Zone Hue Edge)
   -> C' = remap_chroma(C)     (Chroma Lift: different strength when raising chroma)
   -> L untouched
-> Oklab -> XYZ -> linear RGB -> mix -> log(space)
alpha = zone weight a = knee * ceiling * luma_window * hue_kernel, times input alpha
```

The `RGB -> XYZ(D65)` matrix of each space is generated by `tools/gen_matrices.py` from primaries, white point and Bradford adaptation, and sits in the DCTL under `// MAT <NAME>` markers; `tools/verify.py` re-derives them. ACES uses its own white (x 0.32168, y 0.33767, not CIE D60) adapted to D65 with Bradford; DaVinci Wide Gamut and ARRI Wide Gamut 4 are already D65 (no adaptation, the matrix is the manufacturer's own). Oklab uses Ottosson's published `M1`, `M2`, `M2^-1`.

Sources of the transfer functions and primaries: Academy S-2016-001 (ACEScct) and S-2014-003 (ACEScc), Blackmagic *DaVinci Wide Gamut / DaVinci Intermediate* rev. 1.1, ARRI *LogC4 Logarithmic Color Space Specification* (2022-09, rev. 2025-01-23), ITU-R BT.1886 / BT.709-6, IEC 61966-2-1, Lam 1985 (Bradford), and bottosson.github.io/posts/oklab. Oklab is used because its hue is perceptually stable with exposure across oranges and reds, which is where skin lives.

### Hue remap

`d = wrap(h - target)`, `d' = d - s * sin(d) * exp(kappa * (cos d - 1))`, `kappa = 1/width^2`.

A periodic von Mises-shaped attractor. Minimum slope = 1 - s, hence monotonic for any s < 1. Maximum slope about 1.45 with width up to 90 degrees; up to about 1.8 with width 180 and Strength 0.99.

**Asymmetric kernel.** The width varies smoothly and periodically with hue: `w(d) = Width_Red + (Width_Yellow - Width_Red) * sigma(d)` with `sigma(d) = (1 + sin d)/2`, `kappa = 1/w(d)^2`. *Yellow* governs at +90 degrees from the target (hues toward yellow), *Red* at -90 degrees (toward red/magenta); at the target itself and at the opposite hue the width is the average of the two. There are no branches: the field is C-infinity and has no seam at the opposite hue. Mixing the kappas instead of the widths inverts (slope -2.85 at 180/5 degrees) and is not used. Widths are clamped to [1, 180] degrees inside the DCTL: above about 450 degrees the blend would invert.

Note that the nominal width of each side only governs at +/-90 degrees from the target; near the skin line the two sides partly average (for example, Yellow 20 / Red 60 gives half-widths at half height of roughly 34 degrees toward yellow and 75 toward red, against roughly 24 / 76 with a single width each). The narrow side typically comes out about 45 % wider than typed. That is the price of a seamless smooth blend; *Zone Hue Edge* sharpens it where needed.

**Zone Hue Edge.** With `s = 16 * Edge > 0`, the blend becomes
`sigma = sigma0 + m * (sigmaS - sigma0)`, with `sigma0 = (1 + sin d)/2`, `sigmaS = (1 + tanh(s sin d)/tanh(s))/2` and window `m = (1 + cos d)/2`.
The window is 1 at the target and 0 at the opposite hue, so the sharpening is confined to the target side; without it `sin d` also vanishes at d = +/-180 degrees and a second seam appears there. The result is periodic, C-infinity, tends to `sigma0` as s -> 0, and uses the same line in the zone kernel and in the hue shift. With Edge 0 the DCTL takes the plain sinusoidal branch (a ternary on a UI parameter, uniform across the frame, not a mask).

### Weight fields

`s_eff = Strength * knee(C) * ceil(C) * luma_window(L)`

- `knee = C^2 / (C^2 + ChromaMin^2)` rises from 0 at the neutral axis. Prevents gray noise (random hue) from rotating toward orange.
- `ceil = 1 / (1 + (C / ChromaMax)^4)` falls smoothly above the ceiling. Protects very saturated oranges (clothes, wood). At the default it is effectively off.
- Luma window (optional): `wL = knee8(Lc; Min) * ceil8(Lc; Max)`, order-8 rational knee and ceiling on the clamped L (0.5 at each edge). It multiplies the zone field, so hue, chroma and alpha are all affected equally; being constant on each L slice it does not change the slopes of the remaps.

All are C1 continuous fields, not masks: there are no edges.

### Luma tilt

`target_hue(L) = TargetHue + HueTilt * (L - pivot)`

The real skin line is not a plane of constant hue: shadows lean red, highlights lean yellow. With positive tilt the target follows that line. `L` is clamped smoothly to [0, 1.2] with a C-infinity softplus (k = 0.05); inside [0.2, 1.0] it is the identity to within 1e-3.

### Chroma remap

`C' = C * exp(-wC * g)`, with `wC = ChromaStrength * knee * ceil * luma_window * kernel_hue` (clamped to 0.99).

- `kernel_hue = exp((cos d - 1) / w(d)^2)` evaluated at the **original** hue, using the same width `w(d)` as the hue shift: chroma compression acts only near the skin hue and fades away from it.
- `tanh` shape in the log domain: `g` is built from `tanh(f)`; the pull is bounded by a factor `e^(+/- wC)`.
- Bidirectional: raises dull skin and lowers loud skin toward the target chroma.

**Tolerance (deadband).** `u = ln(C/Ct) - k*(L - pivot)`, `k = ChromaTilt/100`, so the effective target is `Ct * e^(k (L - pivot))`, always positive. `delta = ln(1 + Tolerance/100)`, `f = u - delta * tanh(u/delta)`. Near the target `f` is about `u^3 / 3 delta^2`, i.e. about 0, so slope 1 and nothing moves. The band is symmetric in log: `[Ct/(1+p), Ct*(1+p)]`, so 100 % = `[Ct/2, 2 Ct]`. Outside the band the pull is `tanh(u -/+ delta)`: tails converge toward the band edges, not toward Ct, so the core of the skin cluster does not shift even if *Target Chroma* is a bit off.

**Chroma Lift.** `th = tanh(f)`, `r = Lift/100`, `eps = 0.05`:
`g = (1 + r)/2 * th + (1 - r)/2 * eps * lncosh(th/eps)`, `C' = C * exp(-wC * g)`.
`g` has the sign of `th`, and `dg/dth = (1 + r)/2 + (1 - r)/2 * tanh(th/eps)` lies in [r, 1], so the minimum slope of the remap stays 1 - wC. With r = 1 it is exactly `th`. With r = 0 the downward pull is almost entirely kept (about 94 % at th = 0.3) and the residual lift is at most `eps/2 * ln 2` (about 0.017); the blend is C-infinity rather than a `max`.

**Lips Protect.** `cL = C^2 / (C^2 + min^2)`; `wR = clamp(ZoneHueRed, 1, 180) * (1 - 0.9 * Protect * cL)`. The clamp is applied to the UI value before narrowing so the width is C-infinity in C (smallest reachable width 0.5 degrees). The narrowing never exceeds 90 %: with total narrowing the chroma remap inverted (measured slope -0.165 at Protect 1, red range 180, Lift 100). Because the zone kernel and the hue attractor share the same width, the hue map at fixed (L, C) stays a valid hue map with slope >= 1 - strength. The red width now depends on C, so the chroma weight depends on C also through the kernel; the chroma and 2D Jacobian sweeps cover it.

### Output form

`out_linear = in_linear + (F(lab_new) - F(lab))` where `F` is Oklab -> RGB and `lab_new = lab + (lab_remapped - lab) * Mix`. The mix is done in Oklab (L exact at any Mix); the form cancels the round-trip bias of the published matrices, and at Mix 0 returns the input bit-for-bit in linear light (in the log code one float32 ulp remains from the encode/decode round trip). The only pixel-value guard is `h = (C > 0) ? atan2(b, a) : 0`: at C = 0 the output does not depend on h, so it is a numerical guard, not a mask.

### Alpha and Show Shift

`a = wField * kH` is the same field that modulates the effect, without the Strengths, without *Mix* and without the 0.99 clamp (it is a key, not a slope). It is C-infinity in (L, C, h), in [0, 1], periodic at the opposite hue, and 0 on the neutral axis. It is multiplied by the input alpha when *Output Zone Alpha* is on.

*Show Shift* writes `R = 0.5 + dh(deg)/60 * Mix`, `G = 0.5 + ln(C'/C) * Mix` (computed as `-wC * g`, no division), `B = 0.5`, without `encode_log`. At Mix 0 it is exactly mid-gray. With Mix < 1 it shows "the rotation and chroma change that were asked for, times Mix", not the real movement (the mix is done in Cartesian Oklab); at Mix 1 it is exact.

## Design guarantees

These are the invariants the code is written and verified against (`tools/verify.py`):

- **L is never modified.** Only hue and chroma move.
- **Hue remap is monotonic**: slope >= 1 - strength over the whole circle at fixed (L, C), for every combination of widths, Edge and Lips settings; periodic, C-infinity, and the same width line is used in the zone kernel and in the hue shift.
- **Chroma remap is monotonic**: slope > 0 for C in (0, 1] for any parameter combination, including the effective target with Chroma Tilt and pivot (`Ct * e^(+/-1.5)`), Chroma Lift and Lips Protect.
- **The 2D remap (ln C, d) at fixed L is a diffeomorphism**: its Jacobian determinant is > 0 (infimum `(1 - wH)(1 - wC)`, with wH and wC the clamped hue and chroma weights, both <= 0.99). Each axis being monotonic is not enough; a kernel that differs between the hue shift and the chroma weight folds the 2D map.
- **Targets depend only on L.** Hue and chroma targets move with Oklab L around the pivot and with nothing else, so the remap on each L slice stays a diffeomorphism.
- **No hard masks.** Every spatial modulation is a C1 weight field (rational knee, rational ceiling, order-8 rational luma window, rational lips factor, von Mises kernel). The only `if`s are on UI parameters (working space, Output Zone Alpha, Show Shift, Zone Luma Window, Edge > 0), uniform across the frame, plus the `C > 0` guard above and the transfer-function branches that are the published encodings.
- **Strength and effective weights are clamped to 0.99.** At 1.0 the minimum slope is 0 and posterization appears.
- **Alpha is the zone weight**: a C-infinity field in [0, 1], never a hard mask, independent of Strength and Mix, multiplied by the input alpha.
- **Show Shift** is a diagnostic false color, never part of the grade output.

## Limitations

- Per pixel: it does not know the median of the shot. *Target Chroma* is set by hand (*Chroma Tolerance* makes this forgiving). Automatic analysis would need an external script or an OFX plugin.
- It does not touch L. A lightness control would be a third axis with the same philosophy.
- Constant Oklab chroma is not constant vectorscope radius (YCbCr). Rotating hue at fixed C can move the radius slightly on the scope.
- The working space is chosen by hand; the node cannot detect the space of its input.
- The tilt is linear in L; with a high tilt and extreme L the target can move far. L is clamped to [0, 1.2].
- *Show Shift* is not clipped: with high Strengths and wide ranges, R and G leave 0..1.
- ACEScc is not invertible below linear 0: the official encoding sends every linear value <= 0 to the floor -0.3584. At Mix 0 a pixel below the floor does not return bit-for-bit, and with Mix > 0 the effect can push a positive linear channel negative, which ACEScc then flattens at the floor. ACEScct has a linear segment below 0 and does not have this problem: prefer ACEScct in ACES pipelines. The ACEScct decode ceiling of 65504 is not applied.
- The sRGB constants (IEC 61966-2-1) are not exactly continuous: when encoding, the curve steps back about 2.9e-8 at the 0.0031308 cut, so it is invertible except in a band about 7e-9 wide (Mix 0 is not exact there, about 8 ulp). This is the standard's encoding and is not corrected.
- Rec.709 Gamma 2.4 is a pure mirrored power: encoding has infinite slope at 0, so tiny linear values around black (noise, -0.0001) give visible codes. This is inherent to any pure gamma; sRGB has a linear toe and does not suffer from it.
- *Lips Protect* never narrows the red range by more than 90 %.
- A lip or blush with the **same hue** as the skin cannot be separated by any hue control (*Lips Protect*, *Zone Hue Edge*): at d = 0 the kernel is 1 whatever the width. Only *Zone Chroma Max* removes it, and it removes saturated skin too.
- Extremely large input values can overflow float32 in the transfer-function decode and produce NaN in RGB, alpha and *Show Shift*; a NaN alpha propagates to a key. Normal scene-referred and display-referred ranges, including black and negative values, are not affected.
- If the incoming alpha is NaN or outside [0, 1], the output alpha is too (the zone weight itself is always in [0, 1]).
- The alpha output carries the zone weight, but viewing it as a key in Resolve (for example *Use OFX Alpha* + Highlight) has not been fully tested yet. The numpy model in `tools/skinmodel.py` mirrors the DCTL; float32 GPU results may differ slightly from the float64 model.
- Always verify by eye: no numerical test replaces looking at faces and a hue ramp on a monitor.

## Default skin references

Oklab values, computed with the DCTL's own matrices (details and sources in [docs/skin-defaults.md](docs/skin-defaults.md)):

| Reference | Source | Oklab hue |
|---|---|---|
| ColorChecker dark skin | ACES AP0 | 43.0 degrees (L 0.469, C 0.055) |
| ColorChecker light skin | ACES AP0 | 44.5 degrees (L 0.712, C 0.063) |
| Measured real faces | Xiao et al. 2017, 960 people, spectrophotometer | 45.6-53.2 degrees, mean **48.7** degrees |
| Preferred skin | Zeng 2011, observers of three cultures | 44.8-46.2 degrees, mean **45.6** degrees |

The default *Target Hue* of **47 degrees** is the midpoint between measured real faces (48.7) and preferred skin (45.6). The default *Target Chroma* 0.06 comes from the ColorChecker skin patches (0.055 and 0.063). The display transform matters too: ACES 1.x shifts skin about +4 degrees toward yellow on display, ACES 2.0 does not shift it. These are starting points: evaluate on your own material and adjust.

## Glossary

- **Oklab**: a perceptual color space (L lightness, a/b chromatic axes). C = chroma (radius), h = hue (angle).
- **ACEScct / ACEScc**: logarithmic working encodings of ACES. ACEScct has a linear toe; ACEScc is purely logarithmic with a floor below zero.
- **DaVinci Wide Gamut / DaVinci Intermediate**: Resolve's own gamut and log curve (RCM). **AWG4 / LogC4**: gamut and log curve of current ARRI cameras.
- **Bradford**: chromatic adaptation; here it moves the ACES white to the D65 white Oklab is defined on.
- **von Mises**: a periodic bell on the hue circle, `exp(kappa (cos d - 1))`; the shape of the kernel and of the attractor.
- **C1**: continuous with a continuous slope. A C1 field leaves no visible edges; a hard mask does.
- **Alpha / key**: a fourth channel from 0 to 1 saying how much each pixel belongs to a selection. In Resolve, *Use OFX Alpha* is meant to make the node's key output the effect's alpha (not fully tested with this DCTL yet).
- **Monotonic**: the output never goes backwards as the input advances; no inversions or steps between neighboring hues or chromas.

## Development

```
python3 tools/verify.py        # must end in ALL OK (requires numpy)
python3 tools/gen_matrices.py  # prints the matrix block pasted into the DCTL (only if a primary, white or CAT changes)
```

- Requirements: Python 3 and numpy.
- `tools/verify.py` reimplements the curves of the DCTL in float64 and sweeps them over the full UI ranges: matrices read from the DCTL against their derivation, Oklab round trip, hue slope >= 1 - strength, chroma slope > 0, the 2D Jacobian, per-space transfer curves (round trip, continuity at the knee, manufacturer reference values), ColorChecker by space, alpha and Show Shift checks, text-level checks of the DCTL, and negative controls (designs that must fail). It runs in CI and must pass for any change. It peaks at roughly 1 GB of memory and takes about two minutes.
- `tools/gen_matrices.py` derives each space's `RGB -> XYZ(D65)` matrix (primaries normalized per SMPTE RP 177 + Bradford) and the inverse of Oklab's `M1`. Its output is pasted into the DCTL; `verify.py` detects any mismatch.
- `tools/skinmodel.py` is the numpy model of the DCTL shared by the verification script. It mirrors the DCTL by hand: they change together.
- Gotchas of DCTL UI parameters: labels in `DEFINE_UI_PARAMS` must not contain parentheses or commas (the macro breaks with "unknown type of DCTLUIParams definition"). `Resolve.ValidateDCTL` only parses the UI parameters, so a broken kernel can pass it; real compilation happens when the node loads in Resolve.

See [docs/design-notes.md](docs/design-notes.md) for the reasoning behind the design choices and [docs/why-dctl.md](docs/why-dctl.md) for why this is a DCTL and not an OpenFX plugin.

## Contributing

Issues and pull requests are welcome; see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

GPL-3.0-or-later. Copyright (C) 2026 Max Lainz. See [LICENSE](LICENSE).

