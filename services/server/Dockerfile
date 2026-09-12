# syntax=docker/dockerfile:1

FROM python:3.14-slim

# nfs-common is not needed: the kubelet mounts the NFS share, not the container.
RUN apt-get update \
 && apt-get install -y poppler-utils \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir --upgrade pip

# Unprivileged runtime user. UID/GID 1000 is shared with the executor image
# because both write to the same NFS share (see README "Non-root containers").
RUN groupadd --gid 1000 rmn \
 && useradd --uid 1000 --gid rmn --create-home --shell /usr/sbin/nologin rmn \
 && mkdir -p /Server && chown rmn:rmn /Server

WORKDIR /Server

# Dependencies before the source: a code change only rebuilds the COPY layer.
# The pip download cache is a BuildKit cache mount kept across builds.
# Build context is services/ (see docker-compose.yml and docker-publish-all.yml)
# so the shared package next to this service can be copied in.
COPY server/requirements.txt ./requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt gunicorn==23.0.0

# Contracts shared with the executor; its own layer so a change there does
# not reinstall the dependencies above.
COPY common /opt/rmn-common
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps /opt/rmn-common

# The server creates its temp folders next to its code, so the app directory
# belongs to the runtime user (created above, with the user).
COPY --chown=rmn:rmn server/ /Server

ENV ENVIRONMENT=production
ENV PYTHONUNBUFFERED=1
ENV HOME=/home/rmn
# gunicorn's default 30 s worker timeout kills a worker still receiving or
# copying a multi-GB copies zip (5 GB uploads are allowed). The value is the
# same as the ingress proxy-read-timeout; override with the same variable.
ENV GUNICORN_CMD_ARGS="--timeout 1800"

USER rmn

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
