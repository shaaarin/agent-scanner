# Сканер «Agent Skills»: статический анализ навыков (SKILL.md) движками Cisco
# skill-scanner и NVIDIA SkillSpector. Скиллы не запускаются; kind и launcher
# не нужны.
#
# Каждый движок -- свой venv в /opt/engines/*, сервис -- в /opt/service (D-11):
# у движков конфликтующие деревья зависимостей (LiteLLM против LangChain).
# Всё ставится из lock-файлов с хэшами (D-32) и только из колёс; версии
# движков -- D-17, сборка проверена на arm64 (D-28). Обновление lock:
# scripts/compile-locks.sh, затем прогон корпуса eval/ (D-29).
#
# Базовый образ закреплён по digest (multi-arch индекс python:3.12-slim).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

# git -- для установки SkillSpector по коммиту и для клона git-активов (D-42).
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements-cisco.lock requirements-skillspector.lock requirements-service.lock /tmp/locks/

# Cisco AI Defense skill-scanner 2.1.0.
RUN python -m venv /opt/engines/cisco \
    && /opt/engines/cisco/bin/pip install --require-hashes --only-binary=:all: \
        -r /tmp/locks/requirements-cisco.lock \
    && /opt/engines/cisco/bin/skill-scanner --version

# NVIDIA SkillSpector v2.11.2: на PyPI его нет. Зависимости и backend сборки --
# из lock с хэшами; сам пакет -- из git по тегу с проверкой коммита, без
# зависимостей и без изоляции сборки, чтобы ничего не скачалось мимо lock (D-48).
ARG SKILLSPECTOR_REPO=https://github.com/NVIDIA/skillspector
ARG SKILLSPECTOR_TAG=v2.11.2
ARG SKILLSPECTOR_COMMIT=69dcdfb74487d361ba4c811d088cfdea2ff3a9dc
RUN python -m venv /opt/engines/skillspector \
    && /opt/engines/skillspector/bin/pip install --require-hashes --only-binary=:all: \
        -r /tmp/locks/requirements-skillspector.lock \
    && git clone --quiet --depth 1 --branch "$SKILLSPECTOR_TAG" "$SKILLSPECTOR_REPO" /tmp/skillspector \
    && test "$(git -C /tmp/skillspector rev-parse HEAD)" = "$SKILLSPECTOR_COMMIT" \
    && /opt/engines/skillspector/bin/pip install --no-deps --no-build-isolation /tmp/skillspector \
    && rm -rf /tmp/skillspector \
    && /opt/engines/skillspector/bin/skillspector --help >/dev/null

# Сервис.
RUN python -m venv /opt/service \
    && /opt/service/bin/pip install --require-hashes --only-binary=:all: \
        -r /tmp/locks/requirements-service.lock \
    && rm -rf /tmp/locks

ENV PATH=/opt/service/bin:$PATH \
    CISCO_BIN=/opt/engines/cisco/bin/skill-scanner \
    SKILLSPECTOR_BIN=/opt/engines/skillspector/bin/skillspector \
    SKILLS_RULES_DIR=/srv/rules

WORKDIR /srv

# Свои YARA-правила (D-18, D-35): пак для Cisco генерируется из meta правил,
# каждое правило компилируется YARA-X (Cisco) и libyara (SkillSpector) --
# сломанное правило валит сборку, а не скан.
COPY rules/yara ./rules/yara
COPY rules/build_pack.py ./rules/build_pack.py
RUN /opt/engines/cisco/bin/python rules/build_pack.py --compile yara_x --out rules/cisco-pack \
    && /opt/engines/skillspector/bin/python rules/build_pack.py --compile yara

COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
