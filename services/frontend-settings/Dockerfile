FROM nginx:alpine

RUN apk add --no-cache curl

COPY index.html /usr/share/nginx/html/
COPY styles.css /usr/share/nginx/html/
COPY settings.js /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
