import os
from urllib.parse import urlparse

import mysql.connector


def _build_connection_config():
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        parsed_url = urlparse(database_url)

        return {
            "host": parsed_url.hostname or "localhost",
            "port": parsed_url.port or 3306,
            "user": parsed_url.username or "",
            "password": parsed_url.password or "",
            "database": (parsed_url.path or "").lstrip("/"),
        }

    return {
        "host": os.environ.get("DB_HOST", "localhost"),
        "port": int(os.environ.get("DB_PORT", "3306")),
        "user": os.environ.get("DB_USER", "root"),
        "password": os.environ.get("DB_PASSWORD", ""),
        "database": os.environ.get("DB_NAME", "finlytics"),
    }


def get_connection():
    return mysql.connector.connect(**_build_connection_config())
