"""Private onlyStems stream. Run one uvicorn worker: model and stream are shared."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import hmac
import os
import struct
import sys
import time

import numpy as np
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

RATE = 44100
WINDOW = RATE * 4
OVERLAP = RATE // 2
STRIDE = WINDOW - OVERLAP
NAMES = ['drums', 'bass', 'other', 'vocals']
HEADER = struct.Struct('<4sQI')
TOKEN = os.environ.get('ONLYSTEMS_STREAM_TOKEN', '')
# ponytail: one private capture, max four listeners. Multi-user sessions come later.
listeners = set()
producer = None
fetch_proc = None  # ponytail: one share-sheet URL plays at a time
executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='mlx-stream')
model = None
metrics = {'state': 'idle', 'chunks': 0, 'inference_seconds': 0.0, 'capture_peak': 0.0}


def infer(audio):
    global model
    import mlx.core as mx
    from demucs_mlx.model_converter import get_mlx_model
    from demucs_mlx.apply_mlx import apply_model
    if model is None:
        # Reuse HBD's existing fix for the upstream GroupNorm race.
        from app.engine.separate import patch_demucs_kernels
        patch_demucs_kernels()
        model = get_mlx_model('htdemucs')
        if hasattr(model, 'eval'):
            model.eval()
    reference = audio.mean(axis=0)
    mean, std = float(reference.mean()), max(float(reference.std()), 1e-8)
    mix = mx.array(((audio - mean) / std)[None])
    output = apply_model(model, mix, shifts=0, split=False, progress=False)
    mx.eval(output)
    stems = np.asarray(output[0]) * std + mean
    ordered = stems[[list(model.sources).index(name) for name in NAMES]]
    return ordered.transpose(2, 0, 1).reshape(-1, 8).astype('<f4')


class Overlap:
    def __init__(self):
        self.tail = None
        self.fade = (np.sin(np.linspace(0, np.pi / 2, OVERLAP)) ** 2).astype('float32')[:, None]

    def commit(self, stems):
        result = stems[:STRIDE].copy()
        if self.tail is not None:
            result[:OVERLAP] = self.tail * (1 - self.fade) + result[:OVERLAP] * self.fade
        self.tail = stems[STRIDE:].copy()
        return result


def packet(offset, samples):
    return HEADER.pack(b'OS01', offset, len(samples)) + samples.astype('<f4').tobytes()


async def close_listeners(reason):
    peers = list(listeners)
    listeners.clear()
    await asyncio.gather(*(ws.close(code=1012, reason=reason) for ws in peers), return_exceptions=True)


async def broadcast(data):
    async def send(ws):
        try:
            await asyncio.wait_for(ws.send_bytes(data), timeout=1)
        except Exception:
            listeners.discard(ws)
            try:
                await ws.close(code=1013, reason='Playback connection too slow; reconnect')
            except Exception:
                pass
    await asyncio.gather(*(send(ws) for ws in list(listeners)))


@asynccontextmanager
async def lifespan(app):
    if len(TOKEN) < 32:
        raise RuntimeError('Set ONLYSTEMS_STREAM_TOKEN to at least 32 random characters')
    yield
    await close_listeners('Server stopped')
    executor.shutdown(wait=False, cancel_futures=True)


app = FastAPI(lifespan=lifespan)


async def authorize(ws):
    value = ws.headers.get('authorization', '')
    if not hmac.compare_digest(value, 'Bearer ' + TOKEN):
        await ws.close(code=1008)
        return False
    return True


@app.get('/health')
async def health():
    fetching = fetch_proc is not None and fetch_proc.returncode is None
    return {'service': 'onlyStems', **metrics, 'listeners': len(listeners), 'fetching': fetching}


@app.post('/submit')
async def submit(request: Request):
    """Receive one URL from the iOS Share Sheet and play it through the capture pipeline."""
    if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + TOKEN):
        raise HTTPException(status_code=401)
    body = await request.json()
    url = str((body or {}).get('url', '')).strip()
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(status_code=400, detail='Need an http(s) url')
    global fetch_proc
    if producer is not None:
        raise HTTPException(status_code=409, detail='Live capture is connected; stop it first')
    if fetch_proc is not None and fetch_proc.returncode is None:
        raise HTTPException(status_code=409, detail='Already playing a track; wait for it to finish')
    # Isolated subprocess: a yt-dlp or ffmpeg failure can never take the server down.
    fetch_proc = await asyncio.create_subprocess_exec(sys.executable, 'fetch.py', url)
    return {'accepted': url}


@app.websocket('/listen')
async def listen(ws: WebSocket):
    if not await authorize(ws):
        return
    if len(listeners) >= 4:
        await ws.close(code=1013)
        return
    await ws.accept()
    await ws.send_json({'protocol': 'OS01', 'sampleRate': RATE, 'stems': NAMES,
                        'channelsPerStem': 2, 'format': 'float32le', 'prebufferSeconds': 4})
    listeners.add(ws)
    try:
        while True:
            await ws.receive_text()  # Disconnect detection; client sends no commands.
    except WebSocketDisconnect:
        pass
    finally:
        listeners.discard(ws)


@app.websocket('/capture')
async def capture(ws: WebSocket):
    global producer
    if not await authorize(ws):
        return
    if producer is not None:
        await ws.close(code=1008, reason='Capture already connected')
        return
    producer = ws
    await ws.accept()
    metrics.update(state='warming', chunks=0)
    queue = asyncio.Queue(maxsize=100)  # max ten seconds, never unbounded delay

    async def receive():
        try:
            while True:
                raw = await asyncio.wait_for(ws.receive_bytes(), timeout=15)
                if len(raw) != 4410 * 2 * 4:
                    raise ValueError('Expected 100ms stereo float32le at 44100Hz')
                if not np.isfinite(np.frombuffer(raw, dtype='<f4')).all():
                    raise ValueError('Non-finite capture samples')
                metrics['capture_peak'] = round(float(np.max(np.abs(np.frombuffer(raw, dtype='<f4')))), 5)
                queue.put_nowait(raw)
        finally:
            # Wake processing even when capture ends during silence or inference.
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(None)

    reader = asyncio.create_task(receive())
    pending = bytearray()
    ola = Overlap()
    offset = 0
    try:
        while True:
            raw = await queue.get()
            if raw is None:
                await reader
                break
            pending.extend(raw)
            if len(pending) < WINDOW * 8:
                continue
            audio = np.frombuffer(bytes(pending[:WINDOW * 8]), dtype='<f4').reshape(-1, 2).T.copy()
            del pending[:STRIDE * 8]
            if not listeners:
                metrics['state'] = 'capture ready; no listeners'
                ola = Overlap()
                offset += STRIDE
                continue
            start = time.monotonic()
            stems = await asyncio.get_running_loop().run_in_executor(executor, infer, audio)
            metrics.update(state='streaming', chunks=metrics['chunks'] + 1,
                           inference_seconds=round(time.monotonic() - start, 3))
            committed = ola.commit(stems)
            # One message always carries all eight channels at one sample position.
            for a in range(0, len(committed), 4410):
                await broadcast(packet(offset + a, committed[a:a + 4410]))
            offset += len(committed)
    except (WebSocketDisconnect, asyncio.TimeoutError, asyncio.QueueFull, ValueError) as exc:
        metrics['state'] = 'capture stopped: ' + type(exc).__name__
    except Exception:
        metrics['state'] = 'separation failed'
        raise
    finally:
        reader.cancel()
        await asyncio.gather(reader, return_exceptions=True)
        producer = None
        await close_listeners('Capture ended; reconnect after capture resumes')
        try:
            await ws.close()
        except Exception:
            pass
