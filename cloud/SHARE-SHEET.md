# Share a URL to OnlyStems (no copy/paste)

Tap Share in the YouTube app or Safari, pick the Shortcut, and the song plays
through the stem server. The Shortcut POSTs the shared URL to `POST /submit`.

## Server side

`POST /submit` lives in `server.py`. It takes a Bearer token, accepts
`{"url": "..."}`, and launches `fetch.py`, which downloads with yt-dlp and feeds
the audio into the existing `/capture` pipeline. The app's `/listen` stream then
plays the separated stems with live faders, exactly as with AirPlay capture.

Requirements on hbd-server:

- `yt-dlp` in the server venv (`pip install yt-dlp`) and `ffmpeg` on PATH.
- `stream.env` must set `ONLYSTEMS_CAPTURE_URL=ws://172.16.0.36:8093/capture`
  so `fetch.py` can connect back. The server speaks plain ws on the private LAN;
  `fetch.py` uses TLS only when this URL is `wss`. (`ONLYSTEMS_STREAM_TOKEN` is
  already set.)
- Only one source at a time: `/submit` returns 409 if a live capture producer is
  connected or another URL is still playing. Disconnect the live AirPlay capture
  before using share-sheet mode.

## Build the iOS Shortcut (one time, ~2 min)

Needs a StemSplitter build with the **Play in onlyStems Live** action (App Intent
`PlayInOnlyStemsIntent` in `App/StemSplitterApp.swift`).

1. In **Shortcuts**, create a Shortcut named **OnlyStems**.
2. Settings (ⓘ): enable **Show in Share Sheet**, accepted types **URLs**.
3. Add the action **Play in onlyStems Live** and set **Link** to
   **Shortcut Input**.

The app opens straight to the live screen, POSTs `/submit` itself with its
Keychain key, and connects. The Shortcut holds no token. An `Open URLs`
step with `onlystems://live` also works but makes iOS ask "Open in
StemSplitter?" each time; the app's own intent does not.

## Use it

1. In the YouTube app, tap **Share**. Enable **"Start at [current time]"** so the
   URL carries the timestamp; the server seeks there instead of restarting.
2. Scroll to **OnlyStems**, tap it. Mute any stem.

Start-time parsing lives in `fetch.py` (`t`, `start`, `time_continue`), passed to
ffmpeg as `-ss`. Radio streams ignore it.

## Notes

- YouTube shares a `youtube.com/watch?v=...` or `youtu.be/...` link; Safari and
  web apps share the page URL; radio apps share the stream URL. `fetch.py`
  resolves YouTube/page links to a direct audio URL with yt-dlp, and streams raw
  radio/HLS URLs as-is. Continuous radio plays until you submit something else or
  disconnect the capture.
- The public endpoint `https://theaccessvir.us/onlystems/submit` is TLS and
  reachable on cellular; no VPN needed. The LAN path `http://172.16.0.36:8093`
  also works on the home network.
- YouTube extraction uses the deno JS-challenge solver already installed on
  hbd-server. If a specific video returns "unavailable," it is that video, not
  the pipeline.
