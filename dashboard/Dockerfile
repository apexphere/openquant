FROM node:22-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

ARG NEXT_PUBLIC_OPENQUANT_TOKEN
ENV NEXT_PUBLIC_OPENQUANT_TOKEN=$NEXT_PUBLIC_OPENQUANT_TOKEN

RUN npm run build

EXPOSE 3000

CMD ["npm", "start"]
