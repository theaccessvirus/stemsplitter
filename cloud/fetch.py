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
# Resume a dropped connection at the same byte (live and radio streams).
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
    A YouTube Mix never ends, so yt-dlp must not enumerate it: --no-playlist covers a
    watch link inside a Mix (`v=...&list=RD...`), -I 1 a bare Mix or playlist link
    (`playlist?list=RD...`), which plays its first track."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'yt_dlp', '-q', '--no-warnings', '--no-playlist', '-I', '1',
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


async def download(url):
    """Start yt-dlp downloading a finite recording to a local file; return the
    process and the path. yt-dlp fetches YouTube in ranged chunks at network speed
    (a 25 MB, 25-minute track in about 4 s). One long read, as ffmpeg makes, is
    throttled to about 50 KB/s, and read at playback speed it is reset mid-track.
    One fetch runs at a time, so the previous file is cleared here (SIGTERM skips
    cleanup)."""
    shutil.rmtree(WORKDIR, ignore_errors=True)
    os.makedirs(WORKDIR)
    path = os.path.join(WORKDIR, 'track.media')
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'yt_dlp', '-q', '--no-warnings', '--no-playlist', '-I', '1',
        '-f', 'bestaudio/best', '--no-part', '-o', path, '--', url)
    return proc, path


async def feed(download, path, sink):
    """Copy the file into ffmpeg while yt-dlp is still writing it, so playback starts
    on the first bytes rather than after the whole download."""
    finished = asyncio.create_task(download.wait())
    offset = 0
    try:
        while True:
            done = finished.done()  # checked before reading, so an empty read after it is the end
            try:
                with open(path, 'rb') as f:
                    f.seek(offset)
                    data = f.read(1 << 20)
            except FileNotFoundError:
                data = b''
            if data:
                offset += len(data)
                sink.write(data)
                await sink.drain()
            elif done:
                break
            else:
                await asyncio.sleep(0.2)
    except (BrokenPipeError, ConnectionResetError):
        pass  # ffmpeg stopped reading: the track was replaced or the socket closed
    finally:
        sink.close()


async def main(url, start):
    if urlparse(url).scheme not in ('http', 'https'):
        raise ValueError('Need an http(s) url')
    capture_url = os.environ['ONLYSTEMS_CAPTURE_URL']
    token = os.environ['ONLYSTEMS_STREAM_TOKEN']
    # TLS only when the capture endpoint is wss; the private LAN server speaks plain ws.
    ssl_context = ssl.create_default_context() if urlparse(capture_url).scheme == 'wss' else None
    source, finite = await resolve(url)
    # Finite recordings play from the local download; live and raw radio streams
    # are read by ffmpeg directly.
    dl, path = await download(url) if finite else (None, None)
    # -ss before -i: the shared timestamp or an app seek. On the piped download it
    # decodes and drops the skipped audio, which is fast because pacing happens below.
    seek = ['-ss', str(start)] if start > 0 else []
    try:
        async with websockets.connect(
                capture_url, additional_headers={'Authorization': 'Bearer ' + token},
                max_size=65536, max_queue=2, close_timeout=3, ssl=ssl_context) as ws:
            ff = await asyncio.create_subprocess_exec(
                FFMPEG, '-hide_banner', '-loglevel', 'error', *seek,
                *([] if finite else RECONNECT), '-i', 'pipe:0' if finite else source,
                '-ac', '2', '-ar', '44100', '-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1',
                stdin=asyncio.subprocess.PIPE if finite else None,
                stdout=asyncio.subprocess.PIPE)
            feeder = asyncio.create_task(feed(dl, path, ff.stdin)) if finite else None
            loop = asyncio.get_running_loop()
            due = loop.time()
            try:
                while True:
                    data = await ff.stdout.readexactly(CHUNK)
                    await asyncio.wait_for(ws.send(data), timeout=5)
                    # Send at playback speed so the server's 10 s queue never overflows.
                    # After a stall (live source), restart the clock instead of bursting.
                    due = max(due + 0.1, loop.time() - 0.5)
                    await asyncio.sleep(max(0.0, due - loop.time()))
            except asyncio.IncompleteReadError:
                pass  # track ended; drop the final sub-100ms remainder
            finally:
                if feeder:
                    feeder.cancel()
                if ff.returncode is None:
                    ff.terminate()
                    await ff.communicate()
    finally:
        if dl and dl.returncode is None:
            dl.terminate()
            await dl.wait()


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
