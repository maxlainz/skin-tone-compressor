# Contributing

Thanks for your interest in Skin Tone Compressor.

## Issues

Issues are welcome: bug reports, odd results on real footage, feature ideas. For a bug report please include:

- DaVinci Resolve Studio version and operating system
- GPU and driver (or Apple Silicon model)
- The *Working Space* selected and the color management mode of the project
- A screenshot of the node settings (all parameters)
- A screenshot or short description of the problem, ideally with *Output Zone Alpha* + Highlight and *Show Shift* views if the problem is about which pixels are affected

Do not attach client footage or proprietary LUTs.

## Pull requests

- Open pull requests against `main`. `main` is protected: CI must pass before merging.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for commit messages (`feat(dctl): ...`, `fix(verify): ...`, `docs: ...`, `chore: ...`), with the reason for the change in the body.
- Keep one topic per pull request.

### Rules for changes to the DCTL

- Any change to the math must keep `python3 tools/verify.py` ending in `ALL OK` (requires numpy). If you add a new curve or weight field, add or adjust its sweep in `tools/verify.py` in the same pull request.
- The invariants in the README ("Design guarantees") are the contract: hue slope >= 1 - strength, chroma slope > 0, 2D Jacobian > 0, Oklab L untouched, no hard masks. A change that breaks one needs a documented, measured reason.
- The numpy model in `tools/skinmodel.py` mirrors the DCTL by hand; it must change in the same pull request as the DCTL.
- If you change a primary, a white point or the chromatic adaptation, regenerate the matrices with `python3 tools/gen_matrices.py` and paste the output into the DCTL; `verify.py` detects any mismatch.
- Adding a working space requires an official, cited transfer function, its primaries and white in `tools/gen_matrices.py`, and its checks in `tools/verify.py` (round trip, ColorChecker) in the same pull request.
- UI labels in `DEFINE_UI_PARAMS` must not contain parentheses or commas (DCTL macro limitation).
- Do not rename UI labels or variables, or reorder or remove controls, without a major version: renaming or reordering UI parameters can reset values in saved grades. New controls go at the end of their family with a neutral default.
- Compile the DCTL in Resolve before submitting (`ValidateDCTL` only parses the UI parameters), and say which Resolve version you used.

## Releases

Releases are Git tags `vX.Y.Z` following [Semantic Versioning](https://semver.org/), with `SkinToneCompressor.dctl` attached to the GitHub Release. The header line `// Skin Tone Compressor X.Y.Z` of the DCTL must match the tag, and `CHANGELOG.md` gets an entry for the version.

## License

By contributing you agree that your contribution is licensed under GPL-3.0-or-later, like the rest of the project.
