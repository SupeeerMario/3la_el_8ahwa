FROM nginx:1.27-alpine

COPY nginx-conf/nginx.conf /etc/nginx/nginx.conf
