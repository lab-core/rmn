#stage 1
FROM node:22 as node
WORKDIR /app

COPY ng/package*.json ./
RUN npm install

COPY ng/ .
RUN npm run build

#stage 2
FROM nginx:stable-alpine
COPY --from=node /app/dist/rmn /usr/share/nginx/html
COPY ng/viewer-4.5.713.min.mjs /usr/share/nginx/html/assets/
COPY default.conf /etc/nginx/conf.d
