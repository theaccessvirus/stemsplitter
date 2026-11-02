"""Fetch one URL and feed it once through the private capture socket.

Launched by the /submit endpoint from an iOS Share Sheet, or run by hand:
    python fetch.py <url>
yt-dlp resolves the direct audio URL for YouTube watch pages and youtu.be links;
plain radio/HLS stream URLs are streamed as-is. ffmpeg streams either kind at
playback speed, so finite tracks play to the end and radio plays until stopped.
"""
import asyncio
import os
import ssl
import sys
from urllib.parse import urlparse

import websockets

CHUNK = 4410 * 2 * 4  # 100ms stereo float32le at 44100Hz, matching server.py
# launchd gives the service a minimal PATH, so name both binaries explicitly.
# yt-dlp runs as a module of this same venv python; ffmpeg path is overridable.
FFMPEG = os.environ.get('ONLYSTEMS_FFMPEG', '/opt/homebrew/bin/ffmpeg')


async def resolve(url):
    """Ask yt-dlp for the direct media URL; fall back to the URL itself for raw streams."""
    proc = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'yt_dlp', '-q', '--no-warnings', '-g', '-f', 'bestaudio/best',
        '--', url,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    out, _ = await proc.communicate()
    for line in out.decode().splitlines():
        if line.startswith('http'):
            return line.strip()
    return url


async def main(url):
    if urlparse(url).scheme not in ('http', 'https'):
        raise ValueError('Need an http(s) url')
    capture_url = os.environ['ONLYSTEMS_CAPTURE_URL']
    token = os.environ['ONLYSTEMS_STREAM_TOKEN']
    # TLS only when the capture endpoint is wss; the private LAN server speaks plain ws.
    ssl_context = ssl.create_default_context() if urlparse(capture_url).scheme == 'wss' else None
    source = await resolve(url)
    async with websockets.connect(
            capture_url, additional_headers={'Authorization': 'Bearer ' + token},
            max_size=65536, max_queue=2, close_timeout=3, ssl=ssl_context) as ws:
        # -re feeds at playback speed so the server's 10s queue never overflows.
        ff = await asyncio.create_subprocess_exec(
            FFMPEG, '-hide_banner', '-loglevel', 'error', '-re', '-i', source,
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


if __name__ == '__main__':
    asyncio.run(main(sys.argv[1]))
