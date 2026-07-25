FROM node:22-alpine AS build

WORKDIR /app

COPY package.json yarn.lock ./
RUN corepack enable && yarn install --frozen-lockfile

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY --from=build /app/dis