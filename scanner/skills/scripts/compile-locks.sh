#!/bin/sh
# Пересобирает lock-файлы с хэшами (D-32) из requirements-*.in. Запускать при
# смене версии движка (D-17) или зависимостей сервиса, затем -- прогон корпуса
# (eval/, D-29). uv работает в контейнере linux; разрешение универсальное под
# Python 3.12, так что lock годится и для arm64, и для amd64 (D-28).
#
#   scanner/skills/scripts/compile-locks.sh
set -eu
cd "$(dirname "$0")/.."
UV_VERSION=0.9.5
docker run --rm -v "$PWD:/w" -w /w python:3.12-slim sh -c "
  apt-get update -qq >/dev/null && apt-get install -y -qq git >/dev/null &&
  pip install -q uv==$UV_VERSION &&
  for name in service cisco skillspector; do
    uv pip compile --quiet --universal --python-version 3.12 --generate-hashes \
      --no-header --emit-index-url requirements-\$name.in -o requirements-\$name.lock
  done"
# SkillSpector из git хэшем не проверить: ставится отдельно по коммиту (D-48).
sed -i.bak '/^skillspector @ git+/d' requirements-skillspector.lock && rm requirements-skillspector.lock.bak
