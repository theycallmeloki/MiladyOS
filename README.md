# MiladyOS

![F_HolYpbEAA8RPg](https://github.com/theycallmeloki/MiladyOS/assets/3431687/b472633c-37f7-4ab2-8b80-abc639a8ea3c)

milady skinned jenkins with optimized defaults for maximizing gpu utilization accross a cluster


## Instructions to Build:

```
# docker buildx build --platform linux/amd64,linux/arm64 -t ogmiladyloki/miladyos --push .
```


## Instructions to Run: 
```
# docker run -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
```

## Pachyderm bootrstrapped from [edith-cli](https://github.com/theycallmeloki/edith-cli)

### You will need [this script](https://gist.github.com/theycallmeloki/aa4df404c3df85c31dac91216e22f678) at the end of the edith-cli installation

Add the following to the Dockerfile in the root section and build yourself a container, checkout builder.sh

```
# Add kubeconfig file to the docker
ADD kubeconfig.yaml /root/.kube/config

# Add Pachctl config to the container
COPY config.json /root/.pachyderm/config.json
```
