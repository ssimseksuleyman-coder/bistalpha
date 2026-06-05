# Dockerfile — sistemi konteyner olarak her yerde çalıştır.
# Cloud (AWS/GCP/Azure/DigitalOcean), Raspberry Pi, veya herhangi Docker host.
#
# KURULUM:
#   docker build -t bist-alpha -f deploy/Dockerfile .
#   docker run -d --name bist-alpha --restart unless-stopped \
#       -e TZ=Europe/Istanbul \
#       -v $(pwd)/data:/app/data \
#       -v $(pwd)/deniz_inbox:/app/deniz_inbox \
#       -v $(pwd)/portfolios:/app/portfolios \
#       bist-alpha
#
# --restart unless-stopped: konteyner çökerse/host yeniden başlarsa otomatik açılır.

FROM python:3.12-slim

ENV TZ=Europe/Istanbul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Sürekli daemon (scheduler 09:45/14:30/18:30 bekler)
CMD ["python3", "daemon.py"]
