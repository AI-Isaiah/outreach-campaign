"""Vercel Python serverless entrypoint.

Wraps the FastAPI ASGI app via Mangum so Vercel's Lambda-style
runtime can invoke it.  ``lifespan="off"`` because connection
pools cannot persist across cold starts in serverless.
"""

from mangum import Mangum

from src.web.app import app

handler = Mangum(app, lifespan="off")
