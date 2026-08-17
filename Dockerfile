FROM node:22-alpine AS client-build

WORKDIR /app/client
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM node:22-alpine

WORKDIR /app

ENV NODE_ENV=production \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    DATABASE_PATH=/app/data/farmops.db

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY server ./server
COPY --from=client-build /app/client/dist ./client/dist

RUN mkdir -p /app/data && addgroup -S app && adduser -S app -G app && chown -R app:app /app
USER app

EXPOSE 8000

CMD ["node", "server/app.js"]
