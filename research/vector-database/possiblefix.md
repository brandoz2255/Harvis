Cannot connect to Postgres container using psycopg2
Asked 6 years, 7 months ago
Modified 6 years, 7 months ago
Viewed 7k times
Report this ad
5

I have the following setup:

    One simple Flask app in a container

    A Postgres container

Using the following Dockerfiles:

FROM python:alpine3.7

COPY . /app
WORKDIR /app

RUN apk update
RUN apk add --virtual build-deps gcc python3-dev musl-dev
RUN apk add postgresql-dev
RUN pip install -r requirements.txt
RUN apk del build-deps

EXPOSE 5006

CMD ["python", "./app.py"]

And for the db:

FROM postgres:11.1-alpine

COPY create_db.sql /docker-entrypoint-initdb.d/

EXPOSE 5432

This is my docker-compose yaml (mapped ports to host to check the containers work):

version: '3'
services:
    postgres:
        image: ccdb
        build: ccDb
        restart: always
        environment:
            POSTGRES_PASSWORD: password
        ports:
            - "5432:5432"

    top:
        image: ccpytop
        build: ccPyTop
        ports:
            - "5006:5006"

I could successfully connect to the database from my host and I can navigate to the app pages served by the Flask app. The app connects to the db when I navigate to a certain page, so the postgres container has enough time to start.

When I run docker-compose up I get the following thing:

postgres_1  | 2018-12-04 09:45:13.371 UTC [1] LOG:  listening on IPv4 address "0.0.0.0", port 5432
postgres_1  | 2018-12-04 09:45:13.371 UTC [1] LOG:  listening on IPv6 address "::", port 5432
postgres_1  | 2018-12-04 09:45:13.377 UTC [1] LOG:  listening on Unix socket "/var/run/postgresql/.s.PGSQL.5432"
postgres_1  | 2018-12-04 09:45:13.398 UTC [19] LOG:  database system was interrupted; last known up at 2018-12-04 09:42:23 UTC
postgres_1  | 2018-12-04 09:45:13.521 UTC [19] LOG:  database system was not properly shut down; automatic recovery in progress
postgres_1  | 2018-12-04 09:45:13.524 UTC [19] LOG:  redo starts at 0/1680BC8
postgres_1  | 2018-12-04 09:45:13.524 UTC [19] LOG:  invalid record length at 0/1680CA8: wanted 24, got 0
postgres_1  | 2018-12-04 09:45:13.524 UTC [19] LOG:  redo done at 0/1680C70
postgres_1  | 2018-12-04 09:45:13.536 UTC [1] LOG:  database system is ready to accept connections

But when I do the following in the python container

>>> import psycopg2
>>> conn = psycopg2.connect("host=/var/run/postgresql dbname=postgres user=postgres password=password")

I get this:

Traceback (most recent call last):
  File "<stdin>", line 1, in <module>
  File "/usr/local/lib/python3.7/site-packages/psycopg2/__init__.py", line 130, in connect
    conn = _connect(dsn, connection_factory=connection_factory, **kwasync)
psycopg2.OperationalError: could not connect to server: No such file or directory
    Is the server running locally and accepting
    connections on Unix domain socket "/var/run/postgresql/.s.PGSQL.5432"?

I tried running without the host, but I get the same message, with /tmp/ instead of /var/run/. I also tried linking the containers, but I noticed it's a legacy feature and it didn't work anyway.

It's the first time I use docker-compose and I'm pretty much stuck at this point. Any ideas?

    pythonpostgresqldockerdocker-composepsycopg2
    psycopg2
    246 watchers 4.5k questions
    Psycopg is a PostgreSQL postgresql adapter for Python python.

Share
Improve this question
Follow
asked Dec 4, 2018 at 10:00
Cristi's user avatar
Cristi
1,35722 gold badges1818 silver badges3939 bronze badges

    Why host=/var/run/postgresql ?? as far as I have understood the flask app is on a different container ... – 
    Gioachino Bartolotta
    Commented Dec 4, 2018 at 10:18
    Possible duplicate of Django connection to postgres by docker-compose – 
    David Maze
    Commented Dec 4, 2018 at 11:59
    @GioachinoBartolotta because I thought it had to match the output of the postgres container. Noob mistake on my part :) – 
    Cristi
    Commented Dec 4, 2018 at 12:41

Add a comment
1 Answer
Sorted by:
4

You are running 2 separate containers, which are unaware of each other and therefore not able to communicate to each other.

In order to communicate from one container to another, they have to be on the same network. In Docker, you can create your own subnetwork:

docker network create <network-name>

You can then add the containers to the network by adding

--network=<network-name> --network-alias=<network-alias>

to the docker run commands of the containers.

The docker containers can then be accessed by any of the other containers on the same network by its <network-alias>. For you this means that

conn = psycopg2.connect("host=/var/run/postgresql dbname=postgres user=postgres password=password")

changes to

conn = psycopg2.connect("host=<network-alias> dbname=postgres user=postgres password=password")

where network-alias is the alias you've given to the postgres container.

EDIT

Looking at docker-compose networking for the manual on how to do this in docker-compose. Apparently docker-compose sets up its own network on startup. If your docker-compose is located in directory, then docker-compose will create a network directory_default on which the different containers are discoverable by the name you gave them in the docker-compose file. So if you change your python command to

conn = psycopg2.connect("host=postgres dbname=postgres user=postgres password=password")

it should work.
Share
Improve this answer
Follow
edited Dec 4, 2018 at 10:28
answered Dec 4, 2018 at 10:20
SBylemans's user avatar
SBylemans
1,7741313 silver badges2929 bronze badges

    It's not working for me docker run -d --hostname debugger --network br-net --network-alias debugger --name debugger ghoshsayak/local-docker-env:debugger-20240420 .Now exec to debugger container and did $nslookup debugger, got successful AAAA resolution but failed with $telnet debugger 5000. help? – 
    sayak_ghosh90
    Commented Apr 24, 2024 at 14:12 

Which error are you getting? – 
SBylemans
Commented Apr 24, 2024 at 14:23
I am getting this - $ telnet debugger 5000  Trying 172.18.0.2... telnet: Unable to connect to remote host: Connection refused Using docker 26.1.0. Any help will be really appreciated! – 
sayak_ghosh90
Commented Apr 24, 2024 at 14:27
I did the following: docker network create test, docker run --hostname ubuntu2 --network test --network-alias test-alias --name ubuntu2 -ti ubuntu /bin/bash, docker run --hostname ubuntu1 --network test --network-alias test-alias --name ubuntu1 -ti ubuntu /bin/bash. Which creates a network and connects 2 hosts to it. After installing telnet and netcat on both containers, I was able to connect them using their hostnames. Previous answer is from 2018; may be obsolete in the meantime. – 
SBylemans
Commented Apr 24, 2024 at 19:41
Thanks for your reply. I did try $ nc -lp 1234 (on ubuntu1); $ nc -lp 4321 (on ubuntu2); $telnet ubuntu1 1234 (on ubuntu1: Trying 172.20.0.3... telnet: Unable to connect to remote host: Connection refused); $ telnet ubuntu2 4321 (on ubuntu1: Trying 172.20.0.2... telnet: Unable to connect to remote host: Connection refused); $ telnet 172.20.0.2 4321 (on ubuntu1: Connection refused) and vice-versa with the same result unfortunately. Don't understand what's going on! Maybe related to something else not with docker internal. What do you think? I've been struggling with this for quite a few days. – 
sayak_ghosh90
Commented Apr 24, 2024 at 20:31 
