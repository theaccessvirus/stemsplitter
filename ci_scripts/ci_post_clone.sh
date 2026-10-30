#!/bin/sh
# Xcode Cloud: fetch the exact model tested locally, without a Python toolchain.
set -eu
cd "${CI_PRIMARY_REPOSITORY_PATH:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
archive=$(mktemp -t stemsplitter-model)
trap 'rm -f "$archive"' EXIT HUP INT TERM
curl --fail --location --retry 3 --connect-timeout 30 --max-time 600 \
  'https://github.com/theaccessvirus/stemsplitter/releases/download/coreml-htdemucs-v1/htdemucs-coreml-mixed-v1.tar.gz' \
  --output "$archive"
printf '%s  %s\n' '9e045570996ef65024efb82f89dc83e8a99d23da73b38778a683c6299412f383' "$archive" | shasum -a 256 --check
mkdir -p Models
tar -xzf "$archive" -C Models
test -f Models/htdemucs.mlpackage/Manifest.json
