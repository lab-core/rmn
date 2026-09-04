# syntax=docker/dockerfile:1

# Stage 1: build the Angular app. Its output is architecture-independent
# static files, so build once on the native platform of the CI runner instead
# of once per target platform. Running npm under QEMU (arm64 on an amd64
# runner) was 5x slower and flaky: node died with exit code 146.
FROM --platform=$BUILDPLATFORM node:26 AS node
WORKDIR /app

# lockfile + .npmrc (legacy-peer-deps) so the image installs exactly what was tested
COPY ng/package.json ng/package-lock.json ng/.npmrc ./
RUN npm ci

COPY ng/ .
RUN npm run build

# Stage 2: per-platform nginx image serving the built files. The unprivileged
# variant runs nginx as the nginx user (UID 101) and listens on 8080, so the
# container never runs as root (the stock image needs root to bind port 80).
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY --from=node /app/dist/rmn /usr/share/nginx/html
COPY default.conf /etc/nginx/conf.d
COPY assets/* /usr/share/nginx/html/assets/
