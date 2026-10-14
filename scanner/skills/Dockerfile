# Сканер «Agent Skills»: статический анализ навыков (SKILL.md) движками Cisco
# skill-scanner и NVIDIA SkillSpector. Скиллы не запускаются; kind и launcher
# не нужны. Каркас сервиса (подзадача 3); окружения движков в /opt/engines/*,
# lock-файлы с хэшами и git добавит подзадача 4 (D-11, D-17, D-32).
FROM python:3.12-slim
WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
