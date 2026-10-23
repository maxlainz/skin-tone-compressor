# Why a DCTL and not an OFX plugin

A feasibility note on building Skin Tone Compressor as an OpenFX (OFX) plugin instead of a DCTL: what an OFX plugin would give, what it would cost, and the conditions under which it would be worth it. The product stays a DCTL.

## Summary

- **The DCTL covers the product today.** It runs on the GPU in float32 (Resolve compiles it to Metal, CUDA or OpenCL), can read neighboring pixels (texture signature `__TEXTURE__` + `_tex2D`) and can output alpha (a "Transform DCTL with alpha", Resolve 19.1+). Since Resolve 21.1 it can also be **encrypted with an expiry date** from the scripting API (`EncryptDCTL`, output `.dctle`).
- **What OFX would add that DCTL cannot give**: (1) reading other frames (temporal analysis) and whole-frame reductions with state (medians, histograms); (2) **frame analysis** (median hue/chroma of the skin, hue-versus-luma slope) written into parameters by a button; (3) **viewer overlays** (a skin picker, drawing the zone); (4) richer parameters (groups, pages, RGB colors, menus); (5) **knowing the color space of the clip** (OpenFX 1.5 colour management, Resolve 21) and dropping the *Working Space* combo; (6) working in the **free** version of Resolve (DCTL is Studio-only); (7) a closed binary and custom licensing.
- **Real cost** (order of magnitude): a 1:1 port to OFX with a Metal kernel and CPU path, a moderate amount of work; adding analysis and an overlay picker, considerably more; Windows CUDA, more again plus a Windows machine with an NVIDIA GPU to test on. An Apple Developer account (about 99 USD/year) for signed distribution. Permanent maintenance: every major Resolve or macOS release can break the bundle; a DCTL is recompiled by Resolve itself.
- **Recommendation**: stay with the DCTL. Use `EncryptDCTL` if protected distribution is needed, and solve frame analysis with a script against Resolve's scripting API. Reconsider OFX only for the triggers listed at the end.

## 1. What OFX is and what Resolve hands the plugin

OpenFX is the open standard for image-effect plugins (Nuke, Resolve, Vegas, Flame and others). A plugin is a **bundle** (`Name.ofx.bundle`) with a compiled C++ library that Resolve loads from `/Library/OFX/Plugins` (macOS), `C:\Program Files\Common Files\OFX\Plugins` (Windows) or `/usr/OFX/Plugins` (Linux). Resolve lists it in the OpenFX library of the Color page, like third-party plugins such as Dehancer or Neat Video.

Facts checked in the SDK that Blackmagic installs with Resolve 21.1.1 (`Developer/OpenFX`):

| Fact | Source |
|---|---|
| Resolve implements OpenFX 1.4 plus its own GPU extensions; the 1.5 colour headers are included (`ofxColour.h`) | `OpenFX-1.4/include` |
| Four complete examples with **CUDA, OpenCL and Metal** kernels and a CPU path: `GainPlugin`, `TemporalBlurPlugin`, `RandomFrameAccessPlugin`, `DissolveTransitionPlugin`; Xcode, Visual Studio and Makefile projects | SDK README |
| Pixels arrive as **RGBA float32** in GPU memory (Metal buffer / CUDA pointer / OpenCL buffer) | `GainPlugin.cpp`, `render()` |
| The host provides the **Metal command queue** or the **CUDA stream**; the plugin compiles its Metal kernel from text at run time and caches it per queue | `MetalKernel.mm`, `ofxGPURender.h` |
| **Temporal access**: `getFramesNeeded` + `fetchImage(t +/- n)`; there is an example with random frame access | `RandomFrameAccessPlugin.cpp` |
| **Viewer overlay**: `OverlayInteract` with `ofxDrawSuite` (lines, ellipses, text) | `GainPlugin.cpp`, `GainPluginInteract` |
| Wrapper parameter types: Double, Int, Boolean, Choice, StrChoice, RGB, RGBA, String, PushButton, Group, Page, Parametric (curves), Custom | `Support/include/ofxsParam.h` |
| `setNoSpatialAwareness(true)`: the plugin declares each pixel depends only on itself, and **Resolve can run it when generating LUTs** (like a DCTL) | SDK README |
| **OpenFX 1.5 colour management**: the host can tell the plugin the clip's color space (`kOfxImageClipPropColourspace`, ids such as `ACEScct`), and the plugin can ask for the space it wants its pixels in (`kOfxImageClipPropPreferredColourspaces`). Resolve 21 announces these APIs | `ofxColour.h`, Resolve 21 release notes |
| **OpenCL no longer exists on macOS from Resolve 20.3**: on Mac the GPU path is Metal only | Resolve 20.3 release notes |
| DCTL **can be encrypted**: `Resolve.EncryptDCTL(inputPath, {Name, Expiry (ISO 8601), OutputFolder})` and `ValidateDCTL(source)` in the 21.1 scripting API | scripting API stubs |

Not confirmed from a primary source: whether Resolve draws *Parametric* (curve) parameters in the inspector; whether it accepts unsigned bundles on recent macOS; the state of OpenCL on Windows (CUDA is the safe path with NVIDIA). Each is resolved by compiling the `GainPlugin` and querying the host properties from the plugin; that would be the first task of an OFX effort.

## 2. DCTL versus OFX

| Capability | DCTL | OFX |
|---|---|---|
| Per-pixel remap on the GPU in float32 | yes | yes (same kernel in Metal/CUDA) |
| Parameters: sliders, checkbox, combo | yes | yes, plus groups, pages, RGB colors, buttons, text |
| Keyframes in Resolve | yes | yes |
| Neighboring pixels (smoothing the zone weight, skin texture) | **yes**, with the texture signature (`__TEXTURE__` + `_tex2D`, any pixel of the frame); no longer valid as a LUT | yes, plus multi-pass and mipmaps |
| Alpha output (the skin zone as a key for other nodes, *Use OFX Alpha*) | **yes** (transform with alpha, Resolve 19.1+, straight or premultiplied) | yes |
| Other frames (temporal stability of an analysis) | **no** | yes |
| **Frame analysis** (median skin hue/chroma, hue-vs-luma slope) written into parameters by a button | **no** (today: external script via the API) | yes (GPU reduction + `PushButton` + `setValue`) |
| Skin picker in the viewer, drawing the zone or the target line | **no** | yes (overlay with the draw suite) |
| Knowing the clip's color space without a combo | **no** | yes (OpenFX 1.5, Resolve 21) |
| Free Resolve | **no** (Studio) | yes |
| Unreadable code | **yes** (`EncryptDCTL`, with expiry) | yes (binary) |
| Per-user/per-machine licensing | expiry per file, nothing more | whatever is programmed (serial, activation, dongle) |
| Fusion page | a DCTL node exists in Fusion, but different | yes, OFX loads in Fusion and Edit |
| Other hosts (Nuke, Flame) | no | in theory; each host needs its own testing |

What does **not** change is precision. The DCTL already runs in float32 on the same hardware. An OFX is neither "more float" nor faster for a per-pixel remap.

## 3. Cost

Estimates, not measurements.

| Phase | What | Effort | Requirements |
|---|---|---|---|
| 0. Skeleton | Compile `GainPlugin` with Xcode, load it, confirm host properties (parametric, overlay, signing) | small | Xcode; the SDK ships `.xcodeproj` and a Makefile |
| 1. 1:1 port | Translate `transform()` to a Metal kernel (it is C with `_powf`/`_atan2f`: almost literal), an equivalent CPU path, all parameters, `isIdentity` at Mix 0 | moderate | `tools/verify.py` and the numpy model are reused as they are |
| 2. What DCTL cannot do | Analysis with a button (GPU reduction, robust median), overlay picker, drawn zone | largest | UX design; a second reduction kernel |
| 3. Windows CUDA | `CudaKernel.cu`, Visual Studio, testing | moderate | **Windows machine with an NVIDIA GPU and the CUDA Toolkit** |
| 4. Distribution | Developer ID signing + notarization, `.pkg` installer, bundle versioning | small | Apple Developer Program, about 99 USD/year; ad-hoc signing is enough for local use |
| 5. Commercial | Licensing, web, payments, support for machines you do not control | out of scope | business decision |

Recurring cost: each major Resolve (and macOS) can change the loader, the Metal queue or signing; commercial plugins publish new builds per Resolve version. A DCTL is recompiled by Resolve on its own.

Verification cost is the same as today. The invariants (monotonic, no masks, L untouched) live in the numpy model and `tools/verify.py`; an OFX would be a third consumer of the model.

## 4. Limitations and risks

- **Two kernel languages for the same formula** (Metal and CUDA, plus the C++ CPU path): three copies that diverge. Mitigation: write the math once in a pure C header compilable by all three (the DCTL is already close to that) and have `verify.py` read it as it reads the DCTL today.
- **Overlay and parametric parameters not confirmed in Resolve.** If the inspector does not draw curves, an "advanced" UI stays limited to sliders, as in the DCTL.
- **Losing `NoSpatialAwareness`** as soon as neighbors are read: the plugin can no longer go inside an exported LUT. A DCTL with textures has the same property; the per-pixel DCTL does fit in a LUT.
- **Studio-only goes away, but the Mac App Store build of Resolve does not load OFX** (sandbox); the build downloaded from Blackmagic is needed.
- **Windows needs a test machine**: without one nothing can be claimed; NVIDIA drivers and the CUDA version Resolve links against are a classic source of bugs.
- **Signing**: without a Developer ID, a bundle downloaded from outside is quarantined by macOS.
- **Analysis already has a cheaper route**: a script against the Resolve scripting API that measures median hue, chroma and hue-vs-luma slope of the current frame and returns the values to type in. It does not need OFX.

## 5. Portability from day one (if it is ever built)

- Math in a pure C header, with no `#import` and no Metal or CUDA types; the kernels only wrap it.
- Do not use OpenCL at all (gone on macOS). Metal on Mac, CUDA on Windows/Linux, CPU everywhere.
- No absolute paths and no dependencies outside the SDK; the bundle must be a single binary.
- Colour-management properties behind an `if`: if the host does not announce them, fall back to the *Working Space* combo.
- A stable plugin identifier from the start: changing it breaks every project that uses the plugin.

## 6. When an OFX plugin would make sense

The DCTL remains the product. An OFX plugin would make sense when:

1. Users need to **pick skin in the viewer** or see the drawn zone, and the false-color *Show Shift* and the alpha/Highlight view are not enough.
2. **State between clips or frames** is needed (capturing the skin of one shot and applying it to another, temporal stability), which requires buttons, plugin-written parameters or access to other frames. Spatial weighting and skin texture can be prototyped first in a DCTL with textures (`_tex2D`).
3. Someone with the **free Resolve** needs the effect.
4. A real commercial distribution is planned: then OFX plus licensing, with Windows included from the design.
