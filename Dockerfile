# Use an official Jenkins image as a parent image
FROM jenkins/jenkins:lts-jdk11

# Define Pachctl, Caddy versions
ENV PACHCTL_TAG_VER 1.12.5
ENV CADDY_TAG_VER 2.4.6
ENV K3S_VERSION v1.20.4+k3s1

# Switch to root to install additional packages
USER root

# Install Docker client
RUN curl -fsSL https://get.docker.com -o get-docker.sh && \
    chmod +x get-docker.sh && \
    sh get-docker.sh

# Install Ollama
RUN curl https://ollama.ai/install.sh | sh

# Set the working directory back if needed
WORKDIR /

# Install Caddy
RUN curl -L "https://github.com/caddyserver/caddy/releases/download/v${CADDY_TAG_VER}/caddy_${CADDY_TAG_VER}_linux_amd64.tar.gz" -o caddy.tar.gz && \
    tar -xvf caddy.tar.gz && \
    mv caddy /usr/local/bin/ && \
    rm caddy.tar.gz

# Install Pachctl only on amd64
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
    curl -o /tmp/pachctl.deb -L https://github.com/pachyderm/pachyderm/releases/download/v${PACHCTL_TAG_VER}/pachctl_${PACHCTL_TAG_VER}_amd64.deb && \
    dpkg -i /tmp/pachctl.deb || true; \
    fi

# Install kubectl
RUN ARCH=$(dpkg --print-architecture) && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${ARCH}/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/

# Add helm
RUN curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 \
    && chmod +x get_helm.sh && ./get_helm.sh

# Install Avahi (mDNS)
RUN apt-get update && apt-get install -y avahi-daemon avahi-discover avahi-utils libnss-mdns mdns-scan && \
    systemctl enable avahi-daemon

# Install k3s CLI
RUN curl -sfL https://get.k3s.io -o install_k3s.sh && \
    chmod +x install_k3s.sh && \
    INSTALL_K3S_VERSION=${K3S_VERSION} \
    INSTALL_K3S_SKIP_START=true \
    INSTALL_K3S_SKIP_ENABLE=true \
    sh install_k3s.sh

# Install gosu
RUN apt-get update && apt-get install -y gosu

# Install libcap2-bin for setcap utility
RUN apt-get update && apt-get install -y libcap2-bin

# Set capabilities on the k3s binary
RUN setcap 'cap_net_bind_service=+ep' /usr/local/bin/k3s

# Install the Jenkins CLI package
RUN curl -L https://github.com/jenkinsci/plugin-installation-manager-tool/releases/download/2.10.0/jenkins-plugin-manager-2.10.0.jar -o /opt/jenkins-plugin-manager.jar 

# Add the Jenkins Configuration as Code (JCasC) plugin
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt

# Install plugins using plugins.txt
RUN java -jar /opt/jenkins-plugin-manager.jar --plugin-file /usr/share/jenkins/ref/plugins.txt --verbose

# Clean up apt cache for smaller image size
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Switch back to the jenkins user
USER jenkins

# Skip initial setup
ENV JAVA_OPTS -Djenkins.install.runSetupWizard=false

# Add JCasC configuration file
COPY casc.yaml /usr/share/jenkins/ref/casc.yaml
ENV CASC_JENKINS_CONFIG /usr/share/jenkins/ref/casc.yaml
COPY Caddyfile /etc/caddy/Caddyfile

# Switch to root to set permissions
USER root

# Add and set permissions for the startup script
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

# Switch back to the jenkins user (or whichever user you wish to use)
USER jenkins

CMD ["/startup.sh"]
