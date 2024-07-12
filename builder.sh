docker stop miladyos 
docker rm miladyos
docker rmi ogmiladyloki/miladyos 
docker build -t ogmiladyloki/miladyos . 
docker push ogmiladyloki/miladyos 
docker run --gpus all -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
docker ps
docker logs --follow miladyos