# syntax=docker/dockerfile:1

# Build context is services/ (see Dockerfile.dockerignore): the image needs the
# shared package too, to render the enums the webapp compares.

# Stage 0: the TypeScript copy of rmn_common.status, rendered from the Python
# source shipped in this same commit, so the image can never carry a stale
# generated file (the committed copy in ng/src/app/generated serves ng serve,
# ng test and the IDE; the CI checks it is up to date).
FROM python:3.13-alpine AS contracts
COPY common/rmn_common /rmn_common
RUN python -m rmn_common.typescript /contracts/rmn-contracts.ts

# Stage 1: build the Angular app. Its output is architecture-independent
# static files, so build once on the native platform of the CI runner instead
# of once per target platform. Running npm under QEMU (arm64 on an amd64
# runner) was 5x slower and flaky: node died with exit code 146.
FROM --platform=$BUILDPLATFORM node:26 AS node
WORKDIR /app

# lockfile + .npmrc (legacy-peer-deps) so the image installs exactly what was
# tested; npm download cache is a BuildKit cache mount kept across builds.
COPY webapp/ng/package.json webapp/ng/package-lock.json webapp/ng/.npmrc ./
RUN --mount=type=cache,target=/root/.npm npm ci

COPY webapp/ng/ .
COPY --from=contracts /contracts/rmn-contracts.ts src/app/generated/rmn-contracts.ts
RUN npm run build

# Stage 2: per-platform nginx image serving the built files. The unprivileged
# variant runs nginx as the nginx user (UID 101) and listens on 8080, so the
# container never runs as root (the stock image needs root to bind port 80).
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY --from=node /app/dist/rmn /usr/share/nginx/html
COPY webapp/default.conf webapp/security_headers.inc /etc/nginx/conf.d/
COPY webapp/assets/* /usr/share/nginx/html/assets/
