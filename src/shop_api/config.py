"""Settings from the shop-sut contract file (``../shop-sut/.generated/sut.env``).

Environment variables win over the file, so CI can inject values directly.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / "shop-sut" / ".generated" / "sut.env"


class SutNotRunningError(RuntimeError):
    """The contract file is missing: the shop was never started or bootstrapped."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SUT_", extra="ignore")

    medusa_version: str
    backend_url: str
    admin_url: str
    storefront_url: str
    storefront_country: str = Field(min_length=2, max_length=2)
    publishable_key: str = Field(pattern=r"^pk_")
    admin_email: str
    admin_password: str
    region_id: str = Field(pattern=r"^reg_")
    region_currency: str = Field(min_length=3, max_length=3)
    region_usd_id: str = Field(pattern=r"^reg_")
    sales_channel_id: str = Field(pattern=r"^sc_")
    stock_location_id: str = Field(pattern=r"^sloc_")
    db_readonly_url: str
    redis_url: str
    # Test-only signing secret of the local stand (for expired/re-signed token tests).
    jwt_secret: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env_file = Path(os.environ.get("SUT_ENV_FILE", DEFAULT_ENV_FILE))
    if "SUT_BACKEND_URL" not in os.environ and not env_file.exists():
        raise SutNotRunningError(
            f"shop-sut contract file not found: {env_file}\n"
            "Start the shop first:  make -C ../shop-sut up\n"
            "or point SUT_ENV_FILE to another sut.env."
        )
    try:
        return Settings(_env_file=env_file if env_file.exists() else None)
    except ValidationError as exc:
        raise SutNotRunningError(f"invalid shop-sut contract in {env_file}:\n{exc}") from exc
