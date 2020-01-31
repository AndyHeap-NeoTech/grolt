#!/usr/bin/env python
# coding: utf-8

# Copyright (c) 2002-2016 "Neo Technology,"
# Network Engine for Objects in Lund AB [http://neotechnology.com]
#
# This file is part of Neo4j.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import sys

from asyncio import get_event_loop
from logging import INFO, DEBUG
from shlex import quote as shlex_quote
from subprocess import run

import click
from click import Path

from grolt.addressing import Address, AddressList
from grolt.auth import AuthParamType, Auth
from grolt.client import Connection
from grolt.server import Neo4jService, Neo4jDirectorySpec
from grolt.watcher import watch


class AddressParamType(click.ParamType):

    name = "addr"

    def __init__(self, default_host=None, default_port=None):
        self.default_host = default_host
        self.default_port = default_port

    def convert(self, value, param, ctx):
        return Address.parse(value, self.default_host, self.default_port)

    def __repr__(self):
        return 'HOST:PORT'


class AddressListParamType(click.ParamType):

    name = "addr"

    def __init__(self, default_host=None, default_port=None):
        self.default_host = default_host
        self.default_port = default_port

    def convert(self, value, param, ctx):
        return AddressList.parse(value, self.default_host, self.default_port)

    def __repr__(self):
        return 'HOST:PORT [HOST:PORT...]'


class ConfigParamType(click.ParamType):

    name = "NAME=VALUE"

    def __repr__(self):
        return 'NAME=VALUE'


def watch_log(ctx, param, value):
    watch("grolt", DEBUG if value >= 1 else INFO)
    watch("urllib3", DEBUG if value >= 1 else INFO)


@click.group()
def grolt():
    pass


@grolt.command(help="""\
Run a Bolt client.
""")
@click.option("-a", "--auth", type=AuthParamType(), envvar="NEO4J_AUTH")
@click.option("-b", "--bolt-version", default=0, type=int)
@click.option("-s", "--server-addr", type=AddressListParamType(), envvar="BOLT_SERVER_ADDR")
@click.option("-t", "--transaction", is_flag=True)
@click.option("-v", "--verbose", count=True, callback=watch_log, expose_value=False, is_eager=True)
@click.argument("cypher", nargs=-1)
def client(cypher, server_addr, auth, transaction, bolt_version):
    if auth is None:
        auth = Auth(click.prompt("User", default="neo4j"),
                    click.prompt("Password", hide_input=True))
    if bolt_version:
        bolt_versions = [bolt_version]
    else:
        bolt_versions = None
    try:
        with Connection.open(*server_addr or (), auth=auth, bolt_versions=bolt_versions) as cx:
            records = []
            if transaction:
                cx.begin()
            for statement in cypher:
                cx.run(statement, {})
                cx.pull(-1, -1, records)
            if transaction:
                cx.commit()
            cx.send_all()
            cx.fetch_all()
            for record in records:
                click.echo("\t".join(map(str, record)))
    except Exception as e:
        click.echo(" ".join(map(str, e.args)), err=True)
        sys.exit(1)


@grolt.command(context_settings={"ignore_unknown_options": True}, help="""\
Run a Neo4j cluster or standalone server in one or more local Docker 
containers.

If an additional COMMAND is supplied, this will be executed after startup, 
with a shutdown occurring immediately afterwards. If no COMMAND is supplied,
an interactive command line console will be launched which allows direct
control of the service. This console can be shut down with Ctrl+C, Ctrl+D or
by entering the command 'exit'.

A couple of environment variables will also be made available to any COMMAND
passed. These are:

\b
- BOLT_SERVER_ADDR
- NEO4J_AUTH

""")
@click.option("-a", "--auth", type=AuthParamType(), envvar="NEO4J_AUTH",
              help="Credentials with which to bootstrap the service. These "
                   "must be specified as a 'user:password' pair and may "
                   "alternatively be supplied via the NEO4J_AUTH environment "
                   "variable. These credentials will also be exported to any "
                   "COMMAND executed during the service run.")
@click.option("-B", "--bolt-port", type=int,
              help="A port number (standalone) or base port number (cluster) "
                   "for Bolt traffic.")
@click.option("-c", "--n-cores", type=int,
              help="If specified, a cluster with this many cores will be "
                   "created. If omitted, a standalone service will be created "
                   "instead. See also -r for specifying the number of read "
                   "replicas.")
@click.option("-C", "--config", type=ConfigParamType(), multiple=True,
              help="Pass a configuration value into neo4j.conf. This can be "
                   "used multiple times.")
@click.option("-D", "--debug-port", type=int,
              help="The port number (standalone) or base port number (cluster) "
                   "for java remote debugging.")
@click.option("-E", "--debug-suspend", is_flag=True,
              help="The first Neo4j server process (machine a) should hang "
                   "until a connection is made by a remote java debugger. This "
                   "option is only valid if a debug port is specified with -D.")
@click.option("-H", "--http-port", type=int,
              help="A port number (standalone) or base port number (cluster) "
                   "for HTTP traffic.")
@click.option("-i", "--image",
              help="The Docker image tag to use for building containers. The "
                   "repository name can be included before the colon, but will "
                   "default to 'neo4j' if omitted. Note that a Neo4j "
                   "Enterprise Edition image is required for building "
                   "clusters. To pull the latest snapshot, use the pseudo-tag "
                   "'snapshot'. To force a download (in case of caching), add "
                   "a trailing '!'. File URLs can also be passed, which can "
                   "allow for loading images from local tar files.")
@click.option("-I", "--import-dir", type=Path(exists=True, dir_okay=True,
                                              writable=True),
              help="Share a local directory for use by server import.")
@click.option("-L", "--logs-dir", type=Path(exists=True, dir_okay=True,
                                            writable=True),
              help="Share a local directory for use by server logs. A "
                   "subdirectory will be created for each machine.")
@click.option("-n", "--name",
              help="A Docker network name to which all servers will be "
                   "attached. If omitted, an auto-generated name will be "
                   "used.")
@click.option("-P", "--plugins-dir", type=Path(exists=True, dir_okay=True,
                                               writable=True),
              help="Share a local directory for use by server plugins.")
@click.option("-r", "--n-replicas", type=int,
              help="The number of read replicas to include within the "
                   "cluster. This option will only take effect if -c is also "
                   "used.")
@click.option("-S", "--certificates-dir", type=Path(exists=True, dir_okay=True,
                                                    writable=True),
              help="Share a local directory for use by server certificates.")
@click.option("-v", "--verbose", count=True, callback=watch_log,
              expose_value=False, is_eager=True,
              help="Show more detail about the startup and shutdown process.")
@click.argument("command", nargs=-1, type=click.UNPROCESSED)
def server(command, name, image, auth, n_cores, n_replicas,
           bolt_port, http_port, debug_port, debug_suspend, import_dir,
           logs_dir, plugins_dir, certificates_dir, config):
    try:
        dir_spec = Neo4jDirectorySpec(
            import_dir=import_dir,
            logs_dir=logs_dir,
            plugins_dir=plugins_dir,
            certificates_dir=certificates_dir,
        )
        config_dict = dict(item.partition("=")[::2] for item in config)
        with Neo4jService(name, image, auth, n_cores, n_replicas,
                          bolt_port, http_port, debug_port, debug_suspend, dir_spec, config_dict) as neo4j:
            if command:
                run(" ".join(map(shlex_quote, command)), shell=True,
                    env=neo4j.env())
            else:
                neo4j.run_console()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        raise
        click.echo(" ".join(map(str, e.args)), err=True)
        sys.exit(1)


if __name__ == "__main__":
    grolt()