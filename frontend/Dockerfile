# Node.js 환경 설정
FROM node:18 AS build

# 작업 디렉토리 설정
WORKDIR /app
ENV PATH=/app/node_modules/.bin:$PATH

ARG REACT_APP_API_URL
ENV REACT_APP_API_URL=$REACT_APP_API_URL
# package.json 및 package-lock.json 복사 후 의존성 설치
COPY package.json package-lock.json ./
RUN npm install --no-cache

# 프로젝트 코드 복사
COPY . .
RUN npm run build

RUN ls -la /app/build


