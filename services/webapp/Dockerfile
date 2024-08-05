#stage 1
FROM node:18.13 as node
WORKDIR /app

COPY ng/package*.json ./
RUN npm install

COPY ng/ .
RUN npm run prod

#stage 2
FROM nginx:stable-alpine
COPY --from=node /app/dist/cadriciel /usr/share/nginx/html
COPY default.conf /etc/nginx/conf.d
