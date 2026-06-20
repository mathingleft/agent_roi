#!/usr/bin/env bash
# Build dashboard then serve statically (avoids inotify/EMFILE from IDE)
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-5174}"

echo "Building dashboard..."
bash -c "ulimit -n 65536; cd '$DIR' && node_modules/.bin/vite build"

echo "Serving on http://localhost:$PORT"
exec python3 -m http.server "$PORT" --directory "$DIR/dist"
