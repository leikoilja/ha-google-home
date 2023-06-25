FROM ghcr.io/home-assistant/home-assistant:stable
RUN apk add gcc g++
RUN pip3 install glocaltokens
