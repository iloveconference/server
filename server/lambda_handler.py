"""AWS Lambda entry point."""

from mangum import Mangum

from server.main import app

handler = Mangum(app, lifespan="off")
