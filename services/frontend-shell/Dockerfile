FROM nginx:alpine

# Install curl for healthcheck
RUN apk add --no-cache curl

# Copy files
COPY index.html /usr/share/nginx/html/
COPY styles.css /usr/share/nginx/html/
COPY shell.js /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD curl -f http://localhost/ || exit 1
