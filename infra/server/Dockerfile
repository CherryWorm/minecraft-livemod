# A Fabric server with the game and all third-party mods baked in, so it can boot without internet.
FROM eclipse-temurin:25-jre

ARG MINECRAFT_VERSION
ARG FABRIC_LOADER_VERSION
ARG FABRIC_INSTALLER_VERSION

RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends curl python3 \
 && rm -rf /var/lib/apt/lists/*

COPY mods.lock fetch-mods.sh /opt/mc/
RUN bash /opt/mc/fetch-mods.sh /opt/mc/mods.lock server /opt/mc/mods \
 && bash /opt/mc/fetch-mods.sh /opt/mc/mods.lock shadow /opt/mc/mods-shadow

RUN curl -fsSL --retry 3 -o /opt/mc/fabric-server.jar \
    "https://meta.fabricmc.net/v2/versions/loader/${MINECRAFT_VERSION}/${FABRIC_LOADER_VERSION}/${FABRIC_INSTALLER_VERSION}/server/jar"

# --initSettings downloads the game and its libraries, writes default settings and exits.
# It never starts the server, so no EULA answer is needed or given here.
RUN mkdir -p /opt/mc/bake \
 && cd /opt/mc/bake \
 && java -jar /opt/mc/fabric-server.jar --initSettings \
 && rm -f eula.txt server.properties

COPY server/server.properties server/auto-host.json server/entrypoint.sh server/rcon.py /opt/mc/

RUN chmod -R a+rX /opt/mc

WORKDIR /data
ENTRYPOINT ["bash", "/opt/mc/entrypoint.sh"]
