FROM nginx:alpine

# Copy static files
COPY index.html /usr/share/nginx/html/
COPY profile.js /usr/share/nginx/html/
COPY profile.css /usr/share/nginx/html/

# Health check file
RUN echo "OK" > /usr/share/nginx/html/health

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
