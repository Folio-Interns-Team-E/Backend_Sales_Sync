from sqlalchemy.engine import make_url


def async_database_options(raw_url: str, ssl_mode: str = "auto", environment: str = "development"):
    url = make_url(raw_url)
    if url.drivername not in {"postgres", "postgresql", "postgresql+asyncpg"}:
        raise ValueError("DATABASE_URL must use PostgreSQL")
    url = url.set(drivername="postgresql+asyncpg")
    query = dict(url.query)
    url_ssl = query.pop("sslmode", query.pop("ssl", None))
    mode = ssl_mode if ssl_mode != "auto" else url_ssl
    if mode is None and environment.lower() not in {"development", "test"}:
        mode = "require"
    if mode is not None and mode not in {"disable", "allow", "prefer", "require", "verify-ca", "verify-full"}:
        raise ValueError("Unsupported database SSL mode")
    return url.set(query=query), {"ssl": mode} if mode else {}
