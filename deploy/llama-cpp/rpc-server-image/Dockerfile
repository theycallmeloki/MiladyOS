FROM debian:bookworm-slim AS build

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates git cmake build-essential && \
    rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/ggml-org/llama.cpp.git /src

WORKDIR /src
RUN cmake -B build -DGGML_RPC=ON -DBUILD_SHARED_LIBS=OFF -DGGML_NATIVE=OFF -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build --config Release --target rpc-server -j$(nproc)

FROM debian:bookworm-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/bin/rpc-server /usr/local/bin/rpc-server
ENTRYPOINT ["rpc-server"]
CMD ["-H", "0.0.0.0", "-p", "50052"]
