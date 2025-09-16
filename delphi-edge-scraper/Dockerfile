# Dockerfile
FROM node:22-alpine
WORKDIR /app

# Install deps
COPY package*.json ./
RUN npm ci --omit=dev

# Copy source
COPY . .

ENV NODE_ENV=production
EXPOSE 4001

CMD ["node", "server.js"]
