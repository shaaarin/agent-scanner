FROM node:20-slim AS build

WORKDIR /srv

COPY package.json package-lock.json ./
RUN npm install

COPY . .
ARG VITE_CONTROL_API_URL=http://localhost:8000
ENV VITE_CONTROL_API_URL=$VITE_CONTROL_API_URL
RUN npm run build

FROM node:20-slim

WORKDIR /srv
RUN npm install -g serve
COPY --from=build /srv/dist ./dist

EXPOSE 4173
CMD ["serve", "-s", "dist", "-l", "4173"]
