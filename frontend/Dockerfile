FROM node:22-alpine AS build
WORKDIR /app/frontend
COPY frontend/package.json frontend/yarn.lock ./
RUN yarn install --frozen-lockfile
COPY frontend/ .
ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=$REACT_APP_BACKEND_URL
RUN yarn build
FROM nginx:alpine
COPY --from=build /app/frontend/build /usr/share/nginx/html
COPY frontend/nginx.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80