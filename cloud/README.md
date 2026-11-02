# onlyStems Live — private preview

Capture on the Raspberry Pi → encrypted WebSocket → HBD MLX separation →
eight synchronized PCM channels → native iPhone mixer and system output picker.

This is a buffered live preview, not a finished replacement for desktop onlyStems.
It does not record sessions or add them to history. It does not yet implement the
rough-model/quality-model handoff. Same-phone YouTube/AirPlay send plus local
return playback still needs physical-device routing verification. The live screen
must remain open; background playback is not enabled in this preview.

## Running deployment (2026-11-02)

- Public receive URL: `wss://theaccessvir.us/onlystems/listen`
- Public capture URL: `wss://theaccessvir.us/onlystems/capture`
- HBD: `/Users/models/onlystems-live`, `com.models.onlystems-live` system launch daemon,
  running as `models`, bound to `172.16.0.36:8093`.
- Python environment: existing `/Users/models/moses-stems/venv`; PYTHONPATH includes
  `/Users/models/moses-stems/backend` to reuse its Demucs GroupNorm kernel fix.
- Uses the existing cached `htdemucs` demucs-mlx model. One dedicated inference
  thread serializes loading and evaluation. No new weight download required.
- Pi: `~/onlystems-live`, user service `onlystems-capture.service`.
- Reverse proxy: `adamk@vm-ak`, `/home/adamk/apps/theaccessvir-static/nginx.conf`,
  container `theaccessvir-static`. Before-change backup has suffix
  `.before-onlystems-20261102`.
- A random bearer key is required on both WebSockets. Each host has a mode-600
  `stream.env`; the local setup copy is `.work/live/stream.env` (gitignored).
  No credentials in URLs, source control, or app binaries. Native app stores the
  entered key in its device-only Keychain.
- `/onlystems/health` returns operational state, never audio or credentials.

Run `server.py` with one uvicorn worker. Multiple workers would create unrelated
streams and separate GPU models. Current ceiling: one capture and four listeners,
sharing a private key. Add per-session credentials before offering this broadly.
The service stops GPU work when no listeners are connected. Capture still sends
audio until its Pi service is stopped.

## Controls

```sh
# Stop/start capture (does not stop UxPlay playback upstairs)
ssh theaccessvirus@172.16.0.114 'systemctl --user stop onlystems-capture'
ssh theaccessvirus@172.16.0.114 'systemctl --user start onlystems-capture'
# Status
curl -fsS https://theaccessvir.us/onlystems/health
# Restart this stream service only
ssh admin@hbd-server 'sudo -n launchctl kickstart -k system/com.models.onlystems-live'
```

`run.sh` shows the server command. Pi uses `python3 capture.py`, with
`ONLYSTEMS_CAPTURE_URL`, `ONLYSTEMS_STREAM_TOKEN` and optionally
`ONLYSTEMS_PULSE_SOURCE` in its environment. Capture reconnects through systemd.
Native playback stops on connection loss and offers Connect; it never silently
continues a stale timeline.

## Protocol and buffering

Capture messages: exactly 100 ms, stereo, 44,100 Hz, little-endian float32.
Server rejects nonfinite samples and wrong packet sizes. Capture queue is bounded
to ten seconds; overflow ends the session instead of accumulating latency.

Listener first receives JSON describing `OS01`, 44100 Hz, channelsPerStem=2,
format=float32le, stems=[drums,bass,other,vocals]. Each binary packet contains:

- 4 bytes `OS01`
- UInt64 little-endian absolute first sample index
- UInt32 little-endian frame count
- Interleaved float32: drums L/R, bass L/R, other L/R, vocals L/R

HTDemucs windows are four seconds, with a 0.5-second cosine overlap. The server
commits 3.5 seconds per inference, in 100 ms packets. All stems overlap together.
The iPhone validates format, finite samples, and sample continuity, buffers at
least four seconds before starting, and schedules only 0.3 seconds ahead so faders
remain responsive. Because packets arrive in 3.5-second bursts, actual initial
buffering can reach seven seconds. This is deliberately conservative; measure
network jitter before lowering it. Playback queue is capped at ten seconds.
Fader changes have a 128-sample ramp. Mixed output is clipped to [-1,1].

PCM return bandwidth is about 11.3 Mbit/s plus transport overhead. Capture is
about 2.8 Mbit/s. Start on Wi-Fi; compression is future work.

## Validation

```sh
swift test
/Users/adamkershen/theaccessvirus-local/audio/onlyStems/venv/bin/python -m unittest discover -s tests-cloud
xcodebuild -project StemSplitter.xcodeproj -scheme StemSplitter \
  -configuration Debug -sdk iphonesimulator CODE_SIGNING_ALLOWED=NO build
```

A public-path GPU probe rejected an unauthenticated listener with HTTP 403,
then received 70 continuous packets (seven seconds), all finite and correctly
aligned, with nonzero output from a synthetic stereo tone. First packet: 5.69 s
including input buffering and model warmup; second four-second inference: 0.235 s.
This verifies transport and inference, not separation quality on music.

Native simulator validation: iPhone 17 Pro / iOS 26.3 reached
“Playing · cloud separation” from the deployed Pi capture, with its queue varying
around 4–6 seconds. Simulator capture was silent at that point; audible music and
physical-device output routes still require the user's playback test.
Signed Debug iPhone build succeeded; installation on the paired iPhone 16 Pro Max
was blocked by `kAMDMobileImageMounterDeviceLocked` (phone locked).

Live-music validation after the user resumed UxPlay: received ten seconds of
continuous aligned frames, nonzero peaks in all four stems (drums 0.0940,
bass 0.0596, other 0.1447, vocals 0.1283). Warm inference measured 0.243 s for
four seconds of audio. Server restart triggered Pi service recovery (NRestarts=1),
and the native simulator reconnected and resumed playback. Drums solo toggled
on and off in the native UI. Physical audio routing remains unverified.
