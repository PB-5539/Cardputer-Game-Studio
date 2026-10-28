# Build environment: ESP-IDF + MicroPython source, pre-built once so game builds are quick.
# Versions are pinned in build.py (MPY_TAG / IDF_TAG) and passed in as build args.
ARG IDF_TAG=v5.5.2
FROM espressif/idf:${IDF_TAG}

ARG MPY_TAG=v1.29.0
ARG BOARD=ESP32_GENERIC_S3
SHELL ["/bin/bash", "-c"]

RUN git clone --depth 1 --branch "${MPY_TAG}" https://github.com/micropython/micropython.git /mpy
WORKDIR /mpy
RUN make -C mpy-cross -j"$(nproc)"
RUN . "${IDF_PATH}/export.sh" && make -C ports/esp32 submodules
# Warm build so later runs only recompile what the frozen game changes.
RUN . "${IDF_PATH}/export.sh" && make -C ports/esp32 BOARD="${BOARD}" -j"$(nproc)"

COPY build_in_container.sh /usr/local/bin/build_in_container.sh
RUN chmod +x /usr/local/bin/build_in_container.sh
ENTRYPOINT ["/usr/local/bin/build_in_container.sh"]
