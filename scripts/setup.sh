#!/usr/bin/env bash
# One-time setup for the auto_xhs pipeline.
#   - installs Python deps
#   - ensures a libass-enabled ffmpeg (ffmpeg-full on Homebrew)
#   - downloads the xiaohongshu-mcp server + login binaries into vendor/
#   - creates config.yaml / system_prompt.md from the templates
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PY="${PYTHON:-python3}"

echo "==> 1/4 Python dependencies"
"$PY" -m pip install -r requirements.txt

echo "==> 2/4 ffmpeg with libass (caption filters)"
FF="/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg"
if [ ! -x "$FF" ] && ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q " ass "; then
  if command -v brew >/dev/null; then
    echo "    installing ffmpeg-full (this can take a few minutes)..."
    brew install ffmpeg-full
  else
    echo "    WARNING: Homebrew not found. Install an ffmpeg that has libass yourself."
  fi
else
  echo "    ok"
fi

echo "==> 3/4 xiaohongshu-mcp binaries -> vendor/"
mkdir -p vendor
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS-$ARCH" in
  Darwin-arm64) PLAT="darwin-arm64" ;;
  Darwin-x86_64) PLAT="darwin-amd64" ;;
  Linux-x86_64) PLAT="linux-amd64" ;;
  Linux-aarch64|Linux-arm64) PLAT="linux-arm64" ;;
  *) echo "    Unsupported platform $OS-$ARCH; download manually from"
     echo "    https://github.com/xpzouying/xiaohongshu-mcp/releases" ; PLAT="" ;;
esac
if [ -n "$PLAT" ]; then
  BASE="https://github.com/xpzouying/xiaohongshu-mcp/releases/latest/download"
  TARBALL="xiaohongshu-mcp-$PLAT.tar.gz"
  if [ -x "vendor/xiaohongshu-mcp-$PLAT" ]; then
    echo "    already present"
  else
    echo "    downloading $TARBALL (~19MB)"
    curl -fSL "$BASE/$TARBALL" -o "vendor/$TARBALL"
    tar -xzf "vendor/$TARBALL" -C vendor/ && rm -f "vendor/$TARBALL"
    chmod +x "vendor/xiaohongshu-mcp-$PLAT" "vendor/xiaohongshu-login-$PLAT" 2>/dev/null || true
    echo "    extracted server + login binaries to vendor/"
  fi
fi

echo "==> 4/4 config files"
"$PY" run.py init

cat <<EOF

Setup done. Next:
  1) $PY run.py login          # scan the QR with the Xiaohongshu app (or scripts/login.sh)
  2) bash scripts/start_mcp.sh # start the publishing server (keep it running)
  3) $PY run.py doctor         # verify everything is green
EOF
