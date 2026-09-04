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
 && useradd --uid 1000 --gid rmn --create-home --shell /usr/sbin/nologin rmn

WORKDIR /Server

# The server creates its temp folders next to its code, so the app directory
# has to belong to the runtime user.
COPY --chown=rmn:rmn . /Server
RUN chown rmn:rmn /Server

RUN pip install --no-cache-dir -r requirements.txt gunicorn==23.0.0

ENV ENVIRONMENT=production
ENV PYTHONUNBUFFERED=1
ENV HOME=/home/rmn
# gunicorn's default 30 s worker timeout kills a worker still receiving or
# copying a multi-GB copies zip (5 GB uploads are allowed). The value is the
# same as the ingress proxy-read-timeout; override with the same variable.
ENV GUNICORN_CMD_ARGS="--timeout 1800"

USER rmn

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
