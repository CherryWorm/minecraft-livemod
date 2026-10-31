# The agent's only way out to the internet. Anything not on the allowlist is refused, so even an agent that's
# been talked into something can't send data anywhere else.
FROM alpine:3.22

RUN apk add --no-cache tinyproxy

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allowed-hosts /etc/tinyproxy/allowed-hosts

USER tinyproxy
ENTRYPOINT ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
