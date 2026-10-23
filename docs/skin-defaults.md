# Default skin references

Where the default target line of Skin Tone Compressor comes from, and how it compares with measured and preferred skin color. All values are Oklab (computed with the matrices in the DCTL).

**Summary.** The shipped *Target Hue* is **47 degrees** (with a tilt of +12 degrees per unit of Oklab L around L 0.6). It lies between the hue of **real measured faces** (Xiao 2017: 45.6-53.2 degrees, mean 48.7) and the hue of **preferred skin reproduction** (Zeng 2011: 44.8-46.2 degrees, mean 45.6): the midpoint of the two means is 47.2. The ColorChecker skin patches (43.0 and 44.5 degrees) are a few degrees redder, as is preferred skin. Preferences of observers from three cultures differ in **chroma**, not in hue (less than 1.5 degrees apart), so there is no basis for per-culture hue presets; the chroma slider already covers that. The display transform matters: ACES 1.x moves skin about +4 degrees toward yellow on display, ACES 2.0 does not move hue.

## Target line

- Hue: `47 + 12 * (L - 0.6)` degrees
- Chroma: `0.06 * e^(0.6 * (L - 0.6))`

## References in Oklab

The "line" column is the default target hue at the L of each reference; "difference" is line minus reference.

| Reference | Source | Oklab hue | Line at that L | Difference |
|---|---|---|---|---|
| ColorChecker dark skin | ACES AP0 | 43.0 | 45.4 | +2.4 |
| ColorChecker light skin | ACES AP0 | 44.5 | 48.3 | +3.8 |
| Real faces, cheek (Caucasian, Chinese, Kurdish, Thai) | Xiao 2017, table 2 | 45.6 / 45.7 / 48.0 / 53.2 | 47.5-47.8 | +2.1 / +1.9 / -0.5 / -5.4 |
| Real faces, forehead (same groups) | Xiao 2017, table 2 | 47.0 / 48.9 / 50.0 / 51.4 | 47.3-47.6 | +0.6 / -1.6 / -2.7 / -4.0 |
| Mean of the 8 facial means | Xiao 2017 | 48.7 | 47.6 | -1.1 |
| Preferred skin, light / mid / dark images | Zeng 2011, table 4.2.1.3-1 | 46.0 / 46.0 / 45.2 | 48.2 | +2.2 / +2.2 / +3.0 |
| Preferred skin, by observer culture (African, Caucasian, Oriental) | Zeng 2011, table 4.4.1.3-1 | 44.8 / 45.9 / 45.3 | 48.2 | +3.4 / +2.3 / +2.9 |

The line values and differences are computed at the Oklab L of each reference with Target Hue 47 and the +12 degrees per unit L tilt. The reference hues are published or measured values.

Chroma: at L about 0.65 the target line gives 0.062. Real faces measure 0.051-0.057 (the line is roughly 10-20 % above) and preferred skin 0.077-0.085 (the line is roughly 20-25 % below).

What these numbers do **not** measure: the slope of hue with lightness (the Xiao faces are all at L 0.63-0.67; the ColorChecker gives +6.6 degrees per unit L, the same direction as the default 12), and the exact angle of Resolve's vectorscope skin-tone indicator (not confirmed, so not used as a reference).

## The display transform moves hue

The DCTL measures and moves hue in scene space (Oklab of scene-linear XYZ D65). What the colorist sees is that hue **after** the output transform. Measured with the official ACES OpenColorIO configs, Rec.1886 / Rec.709 display, on the Xiao skin colors and the ColorChecker patches:

| Output transform | Hue shift on skin at 0 EV | At +1 EV | Chroma at 0 EV |
|---|---|---|---|
| ACES 1.0 SDR Video (ACES 1.3) | +3.6 to +4.7 degrees (toward yellow) | +6.7 to +11.5 degrees | x0.90-1.00 |
| ACES 2.0 SDR 100 nits | +/-0.4 degrees | +/-0.3 degrees | x0.71-0.82 |

These figures were computed with OpenColorIO's ACES studio configs (1.3 and 2.0) and are indicative.
Consequences: under ACES 1.x a scene target of 47 degrees is seen at about 51 degrees on display; under ACES 2.0 it is seen at 47. Under a DaVinci YRGB timeline without color management the output transform is whatever LUT chain the look uses, which cannot be measured generically. The DaVinci DRT is not in OpenColorIO and has not been measured.

## Cultures and presets

Zeng 2011 had observers of African, Caucasian and Oriental origin judge images of their own and other ethnicities. The preferred hue is the same within 1.5 degrees of Oklab hue for all three cultures; what changes is chroma (Oriental observers prefer about 7 % less chroma than African and Caucasian observers; African observers prefer more chroma in Caucasian and Oriental skin than the others do). Market preference is not the same as the subject's ethnicity: the real skin of the four ethnicities in Xiao differs in yellowness (b*), not in redness (a*), and preferred skin converges to a single point. On that data there is no basis for hue presets by culture; at most a different *Target Chroma* per market, which is already a slider.

## Practical guidance

- 47 degrees is a starting point between real and preferred skin. If your pipeline lifts skin toward yellow on display (ACES 1.x output transform), consider a lower target; under ACES 2.0 or a hue-preserving display transform, the value is seen as set.
- Skin hue in the shot matters more than any population mean: check the vectorscope on the actual face and set *Target Hue* and the tilt accordingly.
- Evaluate on your own footage before changing the default for a whole project.

## Sources

- K. Xiao, J. M. Yates, F. Zardawi, S. Sueeprasan, N. Liao, L. Gill, C. Li, S. Wuerger, "Characterising the variations in ethnic skin colours: a new calibrated data base for human skin", *Skin Research and Technology* 23(1), 2017, table 2 (960 people, spectrophotometer, CIELAB D65/10 degrees). <https://eprints.whiterose.ac.uk/id/eprint/100718/>
- H. Zeng, *Preferred Skin Colour Reproduction*, PhD thesis, University of Leeds, 2011, tables 4.2.1.3-1, 4.2.1.3-2 and 4.4.1.3-1 (a*b* adapted to D50; L* not published, here taken as 65). <https://etheses.whiterose.ac.uk/id/eprint/2090/>
- OpenColorIO 2.6, built-in configs `studio-config-v2.1.0_aces-v1.3_ocio-v2.3` and `studio-config-latest` (ACES 2.0).
- CIELAB to XYZ to Oklab conversion with the Oklab matrices of the DCTL; D50 to D65 with Bradford.
- ColorChecker patches: ACES AP0 values, converted with the ACES white adapted to D65 by Bradford.
