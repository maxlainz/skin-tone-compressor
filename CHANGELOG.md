# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The version of the DCTL is the version of the release; it is also stated in the header line `// Skin Tone Compressor X.Y.Z` of `dctl/SkinToneCompressor.dctl`.

## [Unreleased]

## [1.0.0] - 2026-10-23

Initial public release.

### Added
- `SkinToneCompressor.dctl`: elastic skin tone compressor in Oklab for DaVinci Resolve. Pulls hue and chroma of colors near skin toward a target skin line with a smooth, periodic, monotonic remap; no masks, no inversions, no steps; Oklab L is never modified.
- Working spaces: ACEScct, ACEScc, DaVinci Intermediate, ARRI LogC4, Rec.709 Gamma 2.4 and sRGB. Input and output are in the same space.
- Target controls: Target Hue (default 47 degrees), Target Chroma, and luma tilts of both targets around an adjustable Tilt Pivot Luma.
- Zone controls: asymmetric hue range (Yellow / Red), Zone Hue Edge, Zone Chroma Min / Max, optional Zone Luma Window with Min / Max.
- Strength controls: Hue Strength, Chroma Strength, Chroma Lift, Chroma Tolerance.
- Lips Protect and Lips Chroma Min: narrow the red side of the zone for saturated colors (lips, blush).
- Zone weight output on the alpha channel (Output Zone Alpha), usable as a key through *Use OFX Alpha*; multiplied by the input alpha.
- Show Shift: false-color diagnostic of how far each pixel moves (R hue, G chroma).
- `tools/verify.py`: numerical verification of the DCTL (monotonicity of the hue and chroma remaps, 2D Jacobian, transfer curves, matrices, alpha, Show Shift, negative controls), run in CI.
- `tools/gen_matrices.py`: derives the RGB to XYZ(D65) matrices of each working space.
- `tools/skinmodel.py`: numpy float64 model of the DCTL.
- Documentation: README, design notes, default skin references, and the rationale for DCTL over OpenFX.

[Unreleased]: https://github.com/maxlainz/skin-tone-compressor/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/maxlainz/skin-tone-compressor/releases/tag/v1.0.0
