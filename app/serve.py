"""Container entrypoint; Railway supplies PORT at runtime."""
import os
import uvicorn


def server_options():
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    return {
        "host": "0.0.0.0",
        "port": port,
        # Access logs can include OAuth authorization codes in callback URLs.
        "access_log": False,
        "proxy_headers": True,
        "forwarded_allow_ips": os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1"),
    }


if __name__ == "__main__":
    uvicorn.run("app.main:app", **server_options())
