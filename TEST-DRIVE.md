# Original stack test drive — 2026-10-30

The first test uses the original on-device htdemucs engine, not the Moses server.
No PyTorch is linked or shipped in the iOS app. Python/PyTorch run only on the Mac
to produce the Core ML model.

## Model setup completed locally

The iOS repository omits both weights and conversion tooling. The same author's
Mac repository supplies the matching converter:

- Source: https://github.com/kristerssaulitis/stemsplitter-mac/blob/86ecf67b0f8e0c5d88af07d495e07d7883bef6fe/tools/convert_htdemucs.py
- Local converter: `.work/upstream-mac/tools/convert_htdemucs.py`
- Isolated conversion environment: `.work/coreml-convert-venv`
- Pins: Python 3.11, torch/torchaudio 2.5.1, demucs 4.0.1, coremltools 8.3, numpy <2.
- Full installed versions: `.work/upstream-mac/conversion-requirements.txt`
- Model: `Models/htdemucs.mlpackage`, mixed fp16/fp32, 126,032,627 bytes (120.2 MiB).
- Compiled model for tests: `Models/htdemucs.mlmodelc`.
- Source commit and artifact hashes: `Models/provenance.json`.
- Model outputs: drums, bass, other, vocals. The Swift engine also derives instrumental.

Models and the conversion environment stay gitignored. The app target now has the
model in the location already expected by the original Xcode project.

To rerun conversion in the prepared environment:

```sh
.work/coreml-convert-venv/bin/python .work/upstream-mac/tools/convert_htdemucs.py --precision mixed
```

The converter writes to `.work/upstream-mac/Models`. Copy a new output into `Models`
only when intentionally replacing the current local artifact.

## Validation

- Fixed one upstream Swift type-checking failure in the decorative waveform by
  splitting its numeric expression into explicit intermediate values.
- Swift suite: 135 tests passed, with two real-model tests initially skipped.
- After conversion, both real-model tests passed: non-silent model output plus a
  12-second separation, equal stem lengths, and reconstruction checks.
- Converter reference comparison: frequency output 47.5 dB SNR; time output
  64.9 dB SNR. These are conversion-parity results, not separation-quality scores.
- Simulator app build passed with the bundled model.
- UI test: imported a 20-second music clip through Photos, separated it in 13 seconds
  on the simulator CPU, played stems, toggled Karaoke, and returned to saved history.
  This is a simulator measurement, not iPhone GPU performance.
- Signed iPhone development build passed using `com.theaccessvirus.stemsplitter`.
  The original project bundle ID and your existing signing edits were preserved;
  the development bundle ID was supplied as a build argument.

```sh
swift test
swift test --filter DemucsEngineTests
xcodebuild -project StemSplitter.xcodeproj -scheme StemSplitter \
  -destination 'generic/platform=iOS Simulator' build CODE_SIGNING_ALLOWED=NO
```

The simulator takes the CPU path; its timing is not representative of iPhone GPU
performance. A physical device and listening comparison are needed before calling
this a validated replacement for Moses separation.

## Integration draft

The preliminary Moses client is parked, outside this checkout, at
`../stemsplitter-moses-player-draft-20261030/`. It is not compiled into this test app.
No server, production library, or onlyStems files were changed by this test drive.
