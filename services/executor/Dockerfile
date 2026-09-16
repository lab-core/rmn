# syntax=docker/dockerfile:1

FROM python:3.13-slim

ENV DEBIAN_FRONTEND=noninteractive

# poppler for pdf2image, TeX for the stats report and the cover pages.
# --no-install-recommends leaves out the TeX documentation (about 100 MB);
# the Python packages all ship wheels, so no compiler or -dev headers.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils texlive-latex-base texlive-latex-recommended \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --upgrade pip

# Unprivileged runtime user. UID/GID 1000 is shared with the server image
# because both write to the same NFS share (see README "Non-root containers").
RUN groupadd --gid 1000 rmn \
    && useradd --uid 1000 --gid rmn --create-home --shell /usr/sbin/nologin rmn \
    && mkdir -p /Executor && chown rmn:rmn /Executor

WORKDIR /Executor

# Build context is services/ (see docker-compose.yml and docker-publish-all.yml)
# so the shared package next to this service can be copied in.
COPY executor/requirements.txt ./requirements.txt

# pip's download cache (~1.5 GB of wheels per platform) lives in a BuildKit
# cache mount: it is not baked into the layer (which kept the image small with
# --no-cache-dir before) and it survives across builds, so a change in
# requirements.txt only downloads the new packages.
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

# Contracts shared with the server; its own layer so a change there does not
# reinstall the (large) dependencies above.
COPY common /opt/rmn-common
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps /opt/rmn-common

# The executor creates its per-job tmp_<id> work directories next to its code,
# so the app directory has to belong to the runtime user.
COPY --chown=rmn:rmn executor/ .

ENV ENVIRONMENT=production
# Writable HOME: TeX Live's font cache (~/.texlive*) and matplotlib's config
# directory (~/.config/matplotlib) live there.
ENV HOME=/home/rmn

USER rmn

CMD ["python3", "-m", "job_executor"]
