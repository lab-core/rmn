#stage 1
FROM node:22 as node
WORKDIR /app

COPY ng/package*.json ./
RUN npm install

COPY ng/ .
RUN npm run build

#stage 2
FROM nginx:stable-alpine
COPY --from=node /app/dist/cadriciel /usr/share/nginx/html
COPY default.conf /etc/nginx/conf.d
