FROM nginx:1.27-alpine

COPY nginx-conf/nginx.conf.template /etc/nginx/nginx.conf.template
COPY nginx-conf/render-nginx-conf.sh /docker-entrypoint.d/50-render-nginx-conf.sh
RUN chmod +x /docker-entrypoint.d/50-render-nginx-conf.sh
