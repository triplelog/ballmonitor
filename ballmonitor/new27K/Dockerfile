# 27K server: the game plus the multiplayer API.
#   docker build -t 27k .
#   docker run -d -p 8027:8027 -v 27k-data:/data --name 27k 27k
FROM node:22-alpine
WORKDIR /app
# The formula reader (MathZetta) is the one dependency, for the server and the page.
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY . .
ENV PORT=8027 MP_DATA_DIR=/data
VOLUME /data
EXPOSE 8027
USER node
CMD ["node", "tools/serve.js"]
