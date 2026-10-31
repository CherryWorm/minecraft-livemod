# The public entry point. It authenticates players and holds them during backend restarts.
FROM eclipse-temurin:25-jre

ARG VELOCITY_URL
ARG VELOCITY_SHA256

RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY mods.lock fetch-mods.sh /opt/velocity/
RUN curl -fsSL --retry 3 -o /opt/velocity/velocity.jar "$VELOCITY_URL" \
 && echo "$VELOCITY_SHA256  /opt/velocity/velocity.jar" | sha256sum -c --quiet - \
 && bash /opt/velocity/fetch-mods.sh /opt/velocity/mods.lock velocity /opt/velocity/plugins

COPY velocity/velocity.toml velocity/velocityreconnect.yml velocity/entrypoint.sh /opt/velocity/

RUN chmod -R a+rX /opt/velocity

WORKDIR /data
ENTRYPOINT ["bash", "/opt/velocity/entrypoint.sh"]
