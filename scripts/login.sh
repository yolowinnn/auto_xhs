#!/usr/bin/env bash
# Log in to Xiaohongshu once. Opens a browser with a QR — scan it with the app.
# Cookies are persisted by the server, so you only redo this when they expire.
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

BIN="vendor/xiaohongshu-login-$PLAT"
[ -x "$BIN" ] || { echo "Login binary missing — run scripts/setup.sh first."; exit 1; }
echo "Launching login ($BIN). Scan the QR with the Xiaohongshu app..."
exec "./$BIN"
