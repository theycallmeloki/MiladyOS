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
docker run -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=milady --env JENKINS_ADMIN_PASSWORD=milady -v /var/run/docker.sock:/var/run/docker.sock -v /home/laneone/kubeconfig:/root/.kube/config:ro ogmiladyloki/miladyos
docker ps
docker logs --follow miladyos
