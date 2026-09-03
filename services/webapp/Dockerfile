# syntax=docker/dockerfile:1

# Stage 1: build the Angular app. Its output is architecture-independent
# static files, so build once on the native platform of the CI runner instead
# of once per target platform. Running npm under QEMU (arm64 on an amd64
# runner) was 5x slower and flaky: node died with exit code 146.
FROM --platform=$BUILDPLATFORM node:22 AS node
WORKDIR /app

COPY ng/package.json ./
RUN npm install

COPY ng/ .
RUN npm run build

# Stage 2: per-platform nginx image serving the built files.
FROM nginx:stable-alpine
COPY --from=node /app/dist/rmn /usr/share/nginx/html
COPY default.conf /etc/nginx/conf.d
COPY assets/* /usr/share/nginx/html/assets/
