docker stop miladyos
docker rm miladyos
docker rmi ogmiladyloki/miladyos
docker buildx build --platform linux/amd64,linux/arm64 -t ogmiladyloki/miladyos --push .
docker run -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password --env API_TOKEN=reallythisisthepasswordareyousure -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
docker ps
