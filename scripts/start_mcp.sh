#!/usr/bin/env bash
# Start the xiaohongshu-mcp server (REST + MCP on :18060). Keep it running while
# you publish. Pass --bg to run it detached with logs in state/mcp.log.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS-$ARCH" in
  Darwin-arm64) PLAT="darwin-arm64" ;;
  Darwin-x86_64) PLAT="darwin-amd64" ;;
  Linux-x86_64) PLAT="linux-amd64" ;;
  *) echo "Unsupported platform $OS-$ARCH"; exit 1 ;;
esac

BIN="vendor/xiaohongshu-mcp-$PLAT"
[ -x "$BIN" ] || { echo "Server binary missing — run scripts/setup.sh first."; exit 1; }

if [ "${1:-}" = "--bg" ]; then
  mkdir -p state
  nohup "./$BIN" >> state/mcp.log 2>&1 &
  echo "started in background (pid $!). Logs: state/mcp.log  Health: curl localhost:18060/health"
else
  echo "starting xiaohongshu-mcp on http://localhost:18060 (Ctrl-C to stop)..."
  exec "./$BIN"
fi
