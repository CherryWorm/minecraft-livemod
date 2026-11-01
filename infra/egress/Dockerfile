# The way out for everything in the agent's container, except research, which has web/ and a password. Anything not
# on the allowlist is refused, so even a builder that's been talked into something can't send data anywhere else.
FROM alpine:3.22

RUN apk add --no-cache tinyproxy

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allowed-hosts /etc/tinyproxy/allowed-hosts
COPY entrypoint.sh /entrypoint.sh

USER tinyproxy
ENTRYPOINT ["sh", "/entrypoint.sh"]
