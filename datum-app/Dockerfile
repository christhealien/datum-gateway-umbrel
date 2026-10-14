# DATUM Gateway for Umbrel: upstream source + our web UI (www/) laid over it.
# UPSTREAM_REF empty  -> newest upstream release tag is resolved at build time.
# UPSTREAM_REF=v0.4.1 -> build exactly that tag/branch/commit.
FROM debian:bookworm-slim AS builder
ARG UPSTREAM_REPO=https://github.com/CONVOYMining/datum_gateway.git
ARG UPSTREAM_REF=
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential cmake pkg-config libjansson-dev libmicrohttpd-dev \
      libsodium-dev libcurl4-openssl-dev git ca-certificates python3-minimal \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /build
RUN set -eu; ref="$UPSTREAM_REF"; \
    if [ -z "$ref" ]; then \
      ref=$(git ls-remote --tags --refs "$UPSTREAM_REPO" 'v*' | sed 's|.*refs/tags/||' | sort -V | tail -n1); \
    fi; \
    [ -n "$ref" ] || { echo "could not resolve an upstream release tag" >&2; exit 1; }; \
    echo "$ref" > /upstream-ref; echo "Building upstream $ref"; \
    git clone --depth 1 --branch "$ref" "$UPSTREAM_REPO" src
# Our UI replaces upstream's www/ (same file names; checked by tools/validate_overlay.py)
COPY www/ /build/overlay-www/
RUN cp -r /build/overlay-www/. /build/src/www/
# Per-client Best Share column (skips itself, with a notice, if upstream changed the code it edits)
COPY patches/ /build/patches/
RUN python3 -I /build/patches/best_share.py /build/src && python3 -I /build/patches/fast_notify.py /build/src
WORKDIR /build/src
RUN cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_FLAGS=-DDATUM_API_FOR_UMBREL . && make -j"$(nproc)"

FROM debian:bookworm-slim
ARG VERSION=dev
RUN apt-get update && apt-get install -y --no-install-recommends \
      libjansson4 libmicrohttpd12 libsodium23 libcurl4 python3-minimal libpython3.11-stdlib ca-certificates \
    && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man
WORKDIR /app
COPY --from=builder /build/src/datum_gateway /app/datum_gateway
COPY --from=builder /upstream-ref /app/upstream-ref
COPY entrypoint.sh datum_setup.py datum_web.py /app/
# our own copy of the style sheet and icons, so the sign-in page looks right before the Gateway is up
COPY www/assets/style.css /app/ui/style.css
COPY www/assets/icons/ /app/ui/icons/
RUN chmod +x /app/entrypoint.sh /app/datum_gateway \
    && useradd -u 1000 -m -s /usr/sbin/nologin datum && mkdir -p /data && chown datum /data
USER 1000:1000
LABEL org.opencontainers.image.title="DATUM Gateway (Umbrel)" \
      org.opencontainers.image.source="https://github.com/christhealien/datum-gateway-umbrel" \
      org.opencontainers.image.version="$VERSION"
ENV DATUM_BEHIND_PROXY=1
EXPOSE 23334 7152
VOLUME ["/data"]
ENTRYPOINT ["/app/entrypoint.sh"]
