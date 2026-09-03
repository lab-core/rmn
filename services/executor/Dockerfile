# syntax=docker/dockerfile:1

FROM python:3.12

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y poppler-utils libhdf5-dev texlive-latex-base texlive-latex-recommended \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip setuptools wheel

# Unprivileged runtime user. UID/GID 1000 is shared with the server image
# because both write to the same NFS share (see README "Non-root containers").
RUN groupadd --gid 1000 rmn \
    && useradd --uid 1000 --gid rmn --create-home --shell /usr/sbin/nologin rmn

WORKDIR /Executor

COPY ./requirements.txt ./requirements.txt

# --no-cache-dir: without it pip's download cache (~1.5 GB of wheels per
# platform) is baked into this layer and inflates the image and the CI disk.
RUN pip install --no-cache-dir -r requirements.txt

# The executor creates its per-job tmp_<id> work directories next to its code,
# so the app directory has to belong to the runtime user.
COPY --chown=rmn:rmn . .
RUN chown rmn:rmn /Executor

ENV ENVIRONMENT=production
# Writable HOME: TeX Live's font cache (~/.texlive*) and matplotlib's config
# directory (~/.config/matplotlib) live there.
ENV HOME=/home/rmn

USER rmn

CMD ["python3", "-m", "job_executor"]
