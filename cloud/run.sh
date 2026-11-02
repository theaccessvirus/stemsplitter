#!/bin/zsh
set -eu
cd /Users/models/onlystems-live
set -a
source ./stream.env
set +a
exec /Users/models/moses-stems/venv/bin/python -m uvicorn server:app --host 172.16.0.36 --port 8093 --workers 1 --ws-max-size 65536 --ws-max-queue 4 --no-access-log
