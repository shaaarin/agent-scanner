FROM python:3.12-slim

WORKDIR /srv

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# garak пишет отчёты и кэш данных в $HOME/.garak
ENV HOME=/srv/home
RUN mkdir -p /srv/home /srv/work

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
