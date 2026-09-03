FROM node:22-alpine AS build

WORKDIR /app

COPY package.json yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile

COPY . .

# Vite inlines env vars at build time, so the API origin has to be known here
# rather than at container start. Without this the bundle keeps App.tsx's
# localhost fallback and a deployed frontend calls the visitor's own machine.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
