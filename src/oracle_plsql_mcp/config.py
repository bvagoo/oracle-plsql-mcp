from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    user: str
    password: str
    dsn: str
    default_schema: str | None
    config_dir: str | None
    wallet_location: str | None
    wallet_password: str | None
    pool_min: int = 1
    pool_max: int = 4

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()
        required = {"user": "ORACLE_USER", "password": "ORACLE_PASSWORD", "dsn": "ORACLE_CONNECT_STRING"}
        values = {key: os.getenv(env, "").strip() for key, env in required.items()}
        missing = [env for key, env in required.items() if not values[key]]
        if missing:
            raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
        return cls(
            **values,
            default_schema=_optional("ORACLE_DEFAULT_SCHEMA"),
            config_dir=_optional("ORACLE_CONFIG_DIR"),
            wallet_location=_optional("ORACLE_WALLET_LOCATION"),
            wallet_password=_optional("ORACLE_WALLET_PASSWORD"),
            pool_min=int(os.getenv("ORACLE_POOL_MIN", "1")),
            pool_max=int(os.getenv("ORACLE_POOL_MAX", "4")),
        )


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None
