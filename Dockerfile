FROM python:3.8-alpine

ADD requirements.txt /requirements.txt
RUN apk add \
    musl-dev \
    gcc \
&&  pip install -r requirements.txt

# Uncomment for local development to bake in a config
# ADD config.json /config.json
ADD bot.py /bot.py

CMD ["python","bot.py"]