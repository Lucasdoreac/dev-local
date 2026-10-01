"""Local-only entry point adapting the current API main to Compose Mongo."""

import os

import configmodule

# python-services/main currently builds an Atlas SRV URI from MONGO_HOST,
# MONGO_USERNAME, and MONGO_PASSWORD. The local stack uses unauthenticated
# Mongo on the Compose network, so override the config before importing main.
configmodule.Config.MONGO_URI = os.environ["MONGO_URI"]
configmodule.Config.MONGO_DATABASE = os.environ["MONGO_DATABASE"]

from main import reservation_app as app  # noqa: E402
