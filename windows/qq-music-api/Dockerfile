FROM node:22.22.1-alpine3.22

LABEL maintainer="Kook_Web_Music maintainers"

# Create app directory
WORKDIR /app

COPY package.json .

RUN npm install --registry=https://registry.npmmirror.com

COPY . .

RUN npm run build

EXPOSE 3200

ENTRYPOINT ["npm", "run"]

CMD ["start"]
