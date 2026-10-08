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
# Unbuffered: the handlers log with print(), and a block-buffered stdout meant
# that a pod killed by its liveness probe took every one of those lines with
# it -- the October 2026 crash loop was debugged with zero application
# output.
ENV PYTHONUNBUFFERED=1

USER rmn

# One worker: the rooms are this process's memory, so a second worker would
# serve clients that never see each other's events. Threads give concurrency;
# a handler waiting on Mongo now blocks its own thread and nothing else.
#
# A connected browser holds its thread for the whole session, so --threads is
# the ceiling on simultaneous clients (greenthreads had none). 128 measured at
# ~70 MB against the 256Mi limit: 56 MB idle, 62 MB with 40 live WebSockets.
# --timeout 0 disables the arbiter's per-worker watchdog, which would kill the
# worker while it holds an idle WebSocket or a 25 s poll.
# --worker-tmp-dir: gunicorn puts each worker's heartbeat file in a temp
# directory, and the pod runs with readOnlyRootFilesystem (see the
# securityContext in deployment/socketio.yml), so /tmp is not writable and
# the worker died on "No usable temporary directory found". /dev/shm is a
# tmpfs the runtime mounts rw, and the file is a few bytes.
CMD ["gunicorn", "--worker-class", "gthread", "--workers", "1", \
     "--threads", "128", "--timeout", "0", "--bind", "0.0.0.0:7000", \
     "--worker-tmp-dir", "/dev/shm", "--access-logfile", "-", "app:app"]
