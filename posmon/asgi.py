"""ASGI-точка входа для uvicorn/gunicorn.

Запуск:
    uvicorn posmon.asgi:app --host 127.0.0.1 --port 8600
"""
from .web import create_app

app = create_app()
