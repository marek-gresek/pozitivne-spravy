#!/bin/sh
# Compatibility entry point. Docker worker owns periodic scheduling.
set -eu
exec python /app/worker.py run
