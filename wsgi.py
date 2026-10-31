"""WSGI entry point, e.g.:  waitress-serve --listen=0.0.0.0:8000 wsgi:application"""
from app import create_app

application = create_app()
