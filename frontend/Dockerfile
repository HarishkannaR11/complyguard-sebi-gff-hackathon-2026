#
# Web image: the Vite build served by Caddy (automatic HTTPS when given a domain).
# Build context is ./frontend. The Caddyfile is mounted by deploy/ec2/docker-compose.prod.yml.
#
# VITE_* values are compiled INTO the JavaScript bundle and are readable by every visitor --
# VITE_API_KEY is a convenience for demos, not a secret.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# "/api" = same-origin; the proxy (Caddy / CloudFront) strips the prefix before the API sees it.
ARG VITE_API_URL=/api
ARG VITE_API_KEY=
ENV VITE_API_URL=$VITE_API_URL VITE_API_KEY=$VITE_API_KEY
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
