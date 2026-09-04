#!/bin/bash
# Usage: ./scripts/builder.sh [fresh]
#   (no arg) -> cached build; unchanged layers are skipped on rebuild
#   fresh    -> full rebuild with --no-cache
docker stop miladyos 
docker rm miladyos
docker rmi ogmiladyloki/miladyos
CACHE_FLAG=""
if [ "${1:-}" = "fresh" ]; then CACHE_FLAG="--no-cache"; fi
docker build -t ogmiladyloki/miladyos $CACHE_FLAG .
docker push ogmiladyloki/miladyos 
# Run as the image default user (milady), NOT root: forgejo refuses to run as
# root (RUN_USER=milady in startup.sh's app.ini) and would otherwise skip
# Phase B. Add the host docker group so the wp agent / kaniko / scratch-build
# reach the docker socket.
DOCKER_GID="$(stat -c %g /var/run/docker.sock 2>/dev/null || echo 981)"
docker run -d --name miladyos --privileged --restart=unless-stopped --net=host \
  --group-add "$DOCKER_GID" \
  --env MILADY_ADMIN_ID=milady --env MILADY_ADMIN_PASSWORD=milady \
  -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
docker ps
docker logs --follow miladyos
