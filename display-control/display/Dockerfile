FROM balenalib/raspberrypi4-64-debian:buster

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    xorg \
    xserver-xorg \
    x11-xserver-utils \
    openbox \
    chromium \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    xdg-utils \
    libu2f-udev \
    libvulkan1 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for better package management
RUN apt-get update && apt-get install -y curl && \
    curl -LsSf https://astral.sh/uv/install.sh | sh && \
    echo 'export PATH=$PATH:/root/.local/bin' >> /root/.bashrc

# Add uv to PATH
ENV PATH="/root/.local/bin:${PATH}"

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN uv pip install --system -r requirements.txt

# Install playwright browsers
RUN uv pip install --system playwright && python3 -m playwright install chromium

# Copy application code
COPY app/ .

# Set environment variables
ENV UDEV=1 \
    DISPLAY=:0

# Script to start the display client
COPY start.sh /usr/src/app/
RUN chmod +x /usr/src/app/start.sh

# Command to run the display client
CMD ["/usr/src/app/start.sh"]