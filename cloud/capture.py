"""Run on the Pi. Capture its UxPlay sink monitor into the private server."""
import asyncio
import os
import ssl
from urllib.parse import urlparse
import websockets


async def main():
    url = os.environ['ONLYSTEMS_CAPTURE_URL']
    if urlparse(url).scheme != 'wss':
        raise ValueError('Capture requires a wss:// endpoint')
    token = os.environ['ONLYSTEMS_STREAM_TOKEN']
    source = os.environ.get('ONLYSTEMS_PULSE_SOURCE', 'alsa_output.platform-107c706400.hdmi.hdmi-stereo.monitor')
    async with websockets.connect(url, additional_headers={'Authorization': 'Bearer ' + token},
                                  max_size=65536, max_queue=2, close_timeout=3, ssl=ssl.create_default_context()) as ws:
        process = await asyncio.create_subprocess_exec(
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-f', 'pulse', '-i', source,
            '-ac', '2', '-ar', '44100', '-c:a', 'pcm_f32le', '-f', 'f32le', 'pipe:1',
            stdout=asyncio.subprocess.PIPE)
        try:
            while True:
                data = await asyncio.wait_for(process.stdout.readexactly(4410 * 2 * 4), timeout=15)
                await asyncio.wait_for(ws.send(data), timeout=5)
        finally:
            if process.returncode is None:
                process.terminate()
            try:
                await asyncio.wait_for(process.communicate(), timeout=3)
            except asyncio.TimeoutError:
                if process.returncode is None:
                    process.kill()
                await process.communicate()


if __name__ == '__main__':
    asyncio.run(main())
