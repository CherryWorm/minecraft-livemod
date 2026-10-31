# The web, for research. Open to any public site, but only to whoever holds the password, and only over HTTPS.
# It checks the address a name really resolves to, so no name can lead it to this machine or its network.
FROM alpine:3.22

RUN apk add --no-cache squid openssl

COPY squid.conf /etc/squid/squid.conf
COPY entrypoint.sh /usr/local/bin/web-entrypoint.sh
RUN chmod 755 /usr/local/bin/web-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/web-entrypoint.sh"]
