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

## Build the iOS Shortcut (one time, ~5 min)

1. Open the **Shortcuts** app, tap **+** to create a new Shortcut.
2. Add action **Get Contents of URL**. Set:
   - URL: `https://theaccessvir.us/onlystems/submit` (public, TLS, works anywhere)
   - Method: **POST**
   - Request Body: **JSON**, one field: key `url`, value = **Shortcut Input**
     (tap the field, pick the "Shortcut Input" variable).
   - Headers: add `Authorization` = `Bearer <ONLYSTEMS_STREAM_TOKEN>`.
3. Rename the Shortcut to **OnlyStems**.
4. Tap the Shortcut's settings (ⓘ or the toggles), enable **Show in Share
   Sheet**, and set **Accepted Types** to **URLs** only.

## Use it

1. In the YouTube app (or Safari), tap **Share**.
2. Scroll to **OnlyStems**, tap it.
3. Open the OnlyStems app; the stems are already streaming. Mute any stem.

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
