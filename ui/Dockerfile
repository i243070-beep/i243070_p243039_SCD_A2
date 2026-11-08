# RAHBAR ui image: static chat page served by nginx as a non-root user. Build context: ui/
# nginxinc/nginx-unprivileged runs as UID 101 and listens on 8080 by default.
FROM nginxinc/nginx-unprivileged:1.28.0-alpine

# Our config replaces the whole nginx.conf: it listens on 8080, writes only under /tmp
# (mount an emptyDir at /tmp: the root filesystem is read-only) and logs to stdout/stderr.
COPY nginx.conf /etc/nginx/nginx.conf
COPY index.html /usr/share/nginx/html/index.html

USER 101
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
