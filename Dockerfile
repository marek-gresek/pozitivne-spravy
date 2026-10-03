FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg tzdata && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV TZ=Europe/Prague PYTHONUNBUFFERED=1 DB_FILE=/data/clanky.db AUDIO_DIR=/data/audio
EXPOSE 5001
CMD ["python","bounded_service.py","gunicorn","--workers","2","--threads","2","--bind","0.0.0.0:5001","--timeout","45","app:app"]
