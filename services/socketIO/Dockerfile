# syntax=docker/dockerfile:1

# slim: the full image carries a compiler toolchain (about 850 MB) that a
# service of pure-Python wheels never uses
FROM python:3.14-slim

WORKDIR /SocketIO

# Dependencies before the source: a code change only rebuilds the COPY layer.
COPY ./requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# Unprivileged runtime user. socketIO writes nothing to disk, so the app
# directory can stay root-owned and read-only.
RUN groupadd --gid 1000 rmn \
    && useradd --uid 1000 --gid rmn --create-home --shell /usr/sbin/nologin rmn

ENV ENVIRONMENT=production
ENV HOME=/home/rmn

USER rmn

CMD ["python", "app.py"]
