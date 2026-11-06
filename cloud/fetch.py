"""Fetch one URL and feed it once through the private capture socket.

Launched by the /submit endpoint from an iOS Share Sheet, or run by hand:
    python fetch.py <url> [start-seconds]
yt-dlp resolves the direct audio URL for YouTube watch pages and youtu.be links;
plain radio/HLS stream URLs are streamed as-is. ffmpeg streams either kind at
playback speed, so finite tracks play to the end and radio plays until stopped.
"""
import asyncio
import os
import re
import shutil
import signal
import ssl
import sys
import tempfile
from urllib.parse import parse_qs, urlparse

import websockets

CHUNK = 4410 * 2 * 4  # 100ms stereo float32le at 44100Hz, matching server.py
# launchd gives the service a minimal PATH, so name both binaries explicitly.
# yt-dlp runs as a module of this same venv python; ffmpeg path is overridable.
FFMPEG = os.environ.get('ONLYSTEMS_FFMPEG', '/opt/homebrew/bin/ffmpeg')
# Resume a dropped connection at the same byte (downloads and live streams).
RECONNECT = ['-reconnect', '1', '-reconnect_streamed', '1',
             '-reconnect_on_network_error', '1', '-reconnect_delay_max', '10']
WORKDIR = os.path.join(tempfile.gettempdir(), 'onlystems-fetch')


def start_seconds(url):
    """Seconds to skip, from a YouTube 't'/'start' timestamp (150, 150s, 2m30s, 1h2m3s)."""
    query = parse_qs(urlparse(url).query)
    value = (query.get('t') or query.get('start') or query.get('time_continue') or [''])[0]
    if not value:
        return 0
    if value.isdigit():
        return int(value)
    match = re.fullmatch(r'(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?', value)
    if not match:
        return 0
    h, m, s = (int(g) if g else 0 for g in match.groups())
    return h * 3600 + m * 60 + s


async def resolve(url):
    """Ask yt-dlp for the direct media URL and whether it is a finite recording.
    Raw radio/HLS URLs yt-dlp cannot resolve come back as-is, not finite.
    --no-playlist: links shared from a YouTube Mix carry `list=RD...`, and without it
    yt-dlp enumerates the whole Mix and never returns."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'yt_dlp', '-q', '--no-warnings', '--no-playlist',
        '-f', 'bestaudio/best', '-O', 'is_live', '-O', 'urls', '--', url,
        stdout=asyncio.subprocess.PIPE)  # errors go to the service log
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        raise RuntimeError('yt-dlp did not resolve ' + url + ' within 30 s')
    lines = out.decode().splitlines()
    for line in lines:
        if line.startswith('http'):
            return line.strip(), lines[0].strip() == 'False'
    return url, False


async def download(source):
    """Copy a finite recording to a local file at network speed. Read at playback
    speed, YouTube resets the connection mid-track and ffmpeg's reconnect does not
    always recover, which ends the track early. One fetch runs at a time, so the
    previous file is cleared here rather than on exit (SIGTERM skips cleanup)."""
    shutil.rmtree(WORKDIR, ignore_errors=True)
    os.makedirs(WORKDIR)
    path = os.path.join(WORKDIR, 'track.mka')
    proc = await asyncio.create_subprocess_exec(
        FFMPEG, '-hide_banner', '-loglevel', 'error', *RECONNECT, '-i', source,
        '-vn', '-c:a', 'copy', path)
    if await proc.wait() != 0:
        raise RuntimeError('ffmpeg could not download the track')
    return path


async def main(url, start):
    if urlparse(url).scheme not in ('http', 'https'):
        raise ValueError('Need an http(s) url')
    capture_url = os.environ['ONLYSTEMS_CAPTURE_URL']
    token = os.environ['ONLYSTEMS_STREAM_TOKEN']
    # TLS only when the capture endpoint is wss; the private LAN server speaks plain ws.
    ssl_context = ssl.create_default_context() if urlparse(capture_url).scheme == 'wss' else None
    source, finite = await resolve(url)
    if finite:
        source = await download(source)
    # -ss before -i seeks the resolved stream: the shared timestamp or an app seek.
    seek = ['-ss', str(start)] if start > 0 else []
    async with websockets.connect(
            capture_url, additional_headers={'Authorization': 'Bearer ' + token},
            max_size=65536, max_queue=2, close_timeout=3, ssl=ssl_context) as ws:
        # -re feeds at playback speed so the server's 10s queue never overflows.
        reconnect = [] if finite else RECONNECT
        ff = await asyncio.create_subprocess_exec(
            FFMPEG, '-hide_banner', '-loglevel', 'error', *seek, *reconnect, '-re', '-i', source,
            '-ac', '2', '-ar', '44100', '-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1',
            stdout=asyncio.subprocess.PIPE)
        try:
            while True:
                data = await ff.stdout.readexactly(CHUNK)
                await asyncio.wait_for(ws.send(data), timeout=5)
        except asyncio.IncompleteReadError:
            pass  # track ended; drop the final sub-100ms remainder
        finally:
            if ff.returncode is None:
                ff.terminate()
                await ff.communicate()


def stop_group(*_):
    """SIGTERM from the server's stop_fetch: take yt-dlp and ffmpeg down too,
    instead of leaving them running as orphans."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    os.killpg(0, signal.SIGTERM)


if __name__ == '__main__':
    os.setpgrp()  # own process group, so stop_group never reaches the server
    signal.signal(signal.SIGTERM, stop_group)
    url = sys.argv[1]
    asyncio.run(main(url, int(sys.argv[2]) if len(sys.argv) > 2 else start_seconds(url)))
