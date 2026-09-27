"""Local-only entry point adapting auth_service to Compose Mongo."""

import os

import configmodule

configmodule.Config.MONGO_URI = os.environ["MONGO_URI"]
configmodule.Config.MONGO_DATABASE = os.environ["MONGO_DATABASE"]

from main import auth_app as app  # noqa: E402
