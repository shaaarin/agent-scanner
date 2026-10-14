#!/usr/bin/env bash
# Клонирует легитимные навыки anthropics/skills на зафиксированный коммит в eval/.external/.
# Каталог .external в .gitignore: лицензии у навыков разные (docx/pdf/pptx/xlsx — source-available).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="$HERE/.external/anthropics-skills"
COMMIT="dbd4588f9e1033efb41dad4bef2f7947c8993d44"
mkdir -p "$HERE/.external"
if [ ! -d "$DEST/.git" ]; then
  git clone --quiet https://github.com/anthropics/skills "$DEST"
fi
git -C "$DEST" fetch --quiet origin "$COMMIT" 2>/dev/null || true
git -C "$DEST" checkout --quiet "$COMMIT"
echo "anthropics/skills @ $(git -C "$DEST" rev-parse --short HEAD) -> $DEST"
