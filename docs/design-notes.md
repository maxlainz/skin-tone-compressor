# Design notes

The durable design decisions behind Skin Tone Compressor, and the measurements that justify them. The formulas themselves are in the [README](../README.md); the invariants are enforced by `tools/verify.py`.

## Why Oklab

Skin lives in oranges and reds, where Oklab hue is perceptually stable with exposure. Working in (L, C, h) also makes the goal natural to state: leave L alone and move only hue and chroma. Oklab is used with its canonical published matrices, untouched; the white point is D65, so ACES (white x 0.32168, y 0.33767) is adapted with Bradford, while DaVinci Wide Gamut, ARRI Wide Gamut 4 and Rec.709/sRGB are already D65 and need no adaptation. The published `M2^-1` differs from the exact inverse of `M2` by 6.2e-8 (one float32 ulp at 1.0); it is kept as published, and the output form (below) cancels the resulting bias.

## Monotonic remaps instead of masks

A mask (a key on hue and saturation) draws an edge: colors just inside move, colors just outside do not, and the edge shows. A remap that is monotonic over the whole color cube cannot have that problem: neighbors stay neighbors. So the effect is built only from smooth weight fields and a remap whose slope is bounded away from zero.

- Hue: `d' = d - s sin(d) exp(kappa (cos d - 1))` has minimum slope `1 - s`.
- Chroma: `C' = C exp(-wC g)` with `g` a bounded function of the log-chroma error; minimum slope `1 - wC`.
- Both strengths and effective weights are clamped to 0.99. At exactly 1.0 the minimum slope is 0, a plateau appears, and posterization with it.

## Why tanh for chroma

Three shapes were tried for pulling chroma toward the target: linear (`C + w (Ct - C)`), power (`C (Ct/C)^w`) and `exp(-w tanh(ln(C/Ct)))`. They look equivalent on paper. Only a sweep over the UI ranges showed that the linear and power forms invert (slope below 0): worst case with a low ceiling and a high target (strength 0.99, ceiling 0.05, target 0.2) gave slopes of -3.0 and -3.5, while the `tanh` form held +0.01 (= 1 - 0.99) on the same grid. `tanh` in the log domain is the only one of the three that is monotonic in C for every weight below 1, and it bounds the pull to a factor `e^(+/-wC)`.

## Soft tolerance (deadband)

A hard dead zone around the target chroma would introduce a kink. The soft form `f = u - delta tanh(u/delta)` is C1, has slope 1 at the center, and is about 0 there (`u^3 / 3 delta^2`), so the core of the skin cluster does not move; only the tails converge, and they converge toward the band edges rather than toward the target. The default of 30 % exists because the median chroma of a shot is judged by eye with a 20-30 % error: the tolerance makes the exact value of *Target Chroma* uncritical.

## Targets depend only on L

The hue and chroma targets move with Oklab L around a pivot, and with nothing else. Real skin leans red in shadows and yellow in highlights, and lighter skin has more chroma, so a fixed target would be wrong across a face. But if the target depended on anything else (hue, chroma), the remap on each constant-L slice would stop being a one-dimensional-parameter family of diffeomorphisms and monotonicity would no longer follow from the 1D analysis. With the targets functions of L alone, each L slice is remapped by a fixed map, and the overall map is a diffeomorphism of the cube. The chroma target is exponential in L (`Ct e^(k (L - pivot))`) so it stays positive for any tilt. The effective target is bounded by `Ct e^(+/-1.5)` (|k (L - pivot)| <= 1.5 over the UI range), and the sweeps cover that range.

## Why widths do not vary with luma

Making the kernel width depend on L would be a way to make the zone follow lightness. It was rejected: the remap per L slice would then use a different map on each slice, and the weight field would no longer be constant on a slice, which breaks the slice-wise monotonicity argument. Lightness dependence of the zone is provided instead by a separate soft *Zone Luma Window* that multiplies the weight field: constant on each L slice, so it never changes the slopes of the remaps.

The luma window is of **order 8** (not 4) and **off by default**: an order-4 ceiling over the UI range does not leave the highlights untouched (0.85 on light skin at Max 1.1), while order 8 is useful in L without ceasing to be C-infinity.

## Asymmetric kernel by blending widths

Pulling more from the yellow side than the red side needs a kernel whose width depends on the hue side. Choosing the width by the **sign** of `d` leaves a step of up to 0.82 in the chroma weight at the opposite hue (blue/cyan): a hard mask in disguise. Instead the width is blended smoothly and periodically, `w(d) = wR + (wY - wR) sigma(d)`, `sigma = (1 + sin d)/2`: no branches, C-infinity, no seam. Blending the kappas (`1/w^2`) instead of the widths inverts (slope -2.85 at 180/5 degrees) and is not used. Widths are clamped to [1, 180] degrees because above about 450 degrees the blend inverts. An asymmetric **strength** per side was also rejected: it leaves a C0 corner at the center.

The price of the smooth blend is that the nominal width of each side only governs at +/-90 degrees from the target; near the skin line the two average partially. A more abrupt transition costs monotonicity margin, which is why the abruptness is a separate control (Zone Hue Edge, below) rather than the default.

## Why the zone kernel must be the same in the hue shift and in the chroma weight

The chroma weight multiplies a hue kernel evaluated at the original hue. If that kernel is not exactly the one used by the hue shift, the 2D map (ln C, hue) can fold even when each axis, taken alone, is monotonic. This was measured: giving lips their own kernel inside the chroma weight plus a second hue attractor produced a negative 2D Jacobian determinant (-0.310, at C 0.044, d -34 degrees, Protect 1, range 10 degrees, Lift 100, ceiling 0.05) and gating the hue strength by a hue-dependent kernel gave a hue slope of -2.36. The chosen design shares one kernel: lips protection narrows the red width that both the kernel and the attractor use. With the shared kernel the determinant stays positive; its infimum is `(1 - wH)(1 - wC)`, with wH and wC the clamped hue and chroma weights (both <= 0.99). This is kept as a negative control in `tools/verify.py`.

The chroma factor for lips is of order 2 (`C^2 / (C^2 + min^2)`): with order 4, the chroma slope inverts (-0.154).

The lips narrowing is capped at 90 %: with total narrowing the chroma remap inverted (-0.165 at Protect 1, red range 180, Lift 100), while Protect up to about 0.93 leaves the minimum slope at 0.0105.

## Zone Hue Edge: windowed sharpening

With *Lips Protect* at 1, the sinusoidal width blend lets the yellow width govern near the target, so a lip 15 degrees redder than skin kept 74 % of its zone weight (87 % with a lip of chroma 0.14 and Lips Chroma Min 0.10). The blend is therefore made sharper with a `tanh(s sin d)/tanh(s)` form, `s = 16 Edge`. A raw `tanh` also sharpens at the **opposite** hue, because `sin d` also vanishes at d = +/-180 degrees: a second seam appears there (kernel slope 7.76 per radian against 0.45, 17 times the plain blend with ranges 180/45). Multiplying the difference by the window `m = (1 + cos d)/2` (1 at the target, 0 at the opposite hue) confines the sharpening to the target side; the opposite hue keeps the plain blend (slope within 1.3 times, measured). The same line is used in the zone kernel and in the hue shift.

Measured: hue slope stays at `1 - wgt` for any `s` up to 32; the chroma slope falls only from 0.0105 to 0.0101 at Edge 1; the 2D Jacobian does not move (minimum 5.5e-3 at d = 0, where sigma does not act; no fold up to s = 64 in an exploratory sweep). At Edge 0.5 the lip above keeps 2.1 % and skin at -5 degrees keeps 92 %; at Edge 1, 0.7 % and 77 %. The slider ends at `s = 16` because beyond that nothing is gained on the lip and skin is lost. Making the abruptness depend on C through Protect was rejected: it would add a cross-term to the Jacobian for no gain.

## Lift: a smooth absolute value, not a max

*Chroma Lift* lets chroma be lowered at full strength but raised at a fraction of it. The blend is `g = (1 + r)/2 th + (1 - r)/2 eps lncosh(th/eps)` with `eps = 0.05`: a C-infinity replacement for `max`, with `dg/dth` in [r, 1], so the minimum slope of the remap stays `1 - wC`. A simpler form, `th ((1 + r)/2 + (1 - r)/2 th)`, lifted up to 1/8 at Lift 0 and halved the desaturation near the target, so it was rejected. Lift is expressed as a percentage of *Chroma Strength* (not as a second strength) so that the default of 100 is the symmetric behavior and the slider reads as "how much raising is allowed".

## Output form and Mix

The output is `lin + (F(lab_new) - F(lab))` and the mix is done in Oklab. This keeps L exact at any Mix, makes Mix 0 an exact bypass in linear light (one float32 ulp remains in the log code from the transfer function round trip) and cancels the round-trip bias of the matrices in float64. The cost is formal: for out-of-gamut pixels with L < 0 the Jacobian can dip to about -1e-7, so monotonicity holds to about 4e-7 relative, below float32 rounding.

## Smooth clamps and guards

- L is clamped to [0, 1.2] for the tilts with a C-infinity softplus (k = 0.05). It is the identity inside [0.2, 1.0]. A `tanh`-based clamp was rejected because it reduces the effective tilt to 66 % at L 0.2 and 1.0, which is a behavior change, not a clamp.
- The only per-pixel guard is `C > 0 ? atan2 : 0`: at C = 0 the output does not depend on hue. There is no branch on `C` in the chroma remap (`u = ln(max(C, 1e-12)/Ct)`), because such a branch produced a jump of a factor e^0.99 at C = 1e-6 when the knee was 0.
- The argument of `tanh(u/delta)` is clamped to +/-20 (`tanh(20) = 1` in float32) so that fast-math backends cannot produce NaN.

## Alpha is the zone weight, without Strength

The alpha is the zone weight `a = wField kH`: the field that modulates the effect, without the Strengths, without Mix and without the 0.99 clamp. It says which pixels are skin, not how much they move, so it works as a key for other nodes even when Strength is 0. It is multiplied by the input alpha so an upstream key or window is respected. *Zone Chroma Min* has a lower bound of 0.001: with 0 the field is discontinuous on the neutral axis (measured alpha 0.55-0.72 on exact grays across L, and speckle at C about 1e-9), contradicting the "C1 field, no mask" contract; the UI minimum is raised instead of changing the formula. *Show Shift* exists because it shows something Resolve cannot (how much and in which direction each pixel moves), whereas a view of the zone itself is already available through *Use OFX Alpha* and Highlight.

## ACEScct preferred over ACEScc

ACEScc is not invertible below linear 0 (the standard sends all linear values <= 0 to a floor). That is the standard's encoding rather than a mask of this effect, but it means Mix 0 is not an exact bypass below the floor and the effect can push a positive channel negative where ACEScc flattens it. ACEScct has a linear segment below the toe and does not have the problem.

## Display-referred spaces

Rec.709 Gamma 2.4 and sRGB use mirrored (odd) transfer functions so that they are strictly increasing and invertible over all real numbers; this keeps values above 1 and below 0 processable without clipping, and the mirror is a function of the value's sign, not a branch with a different effect. Rec.709 uses BT.1886 with black level 0; sRGB uses the IEC 61966-2-1 piecewise function.

## Measure before claiming

Claims about a curve, Oklab or ACES behavior are measured with a sweep in `tools/verify.py` before they are written into the DCTL or the docs. The three chroma shapes above looked equivalent on paper; only the sweep showed two of them invert. Negative controls (designs that are expected to fail a sweep) are kept in the script so the sweeps are known to be able to fail.
