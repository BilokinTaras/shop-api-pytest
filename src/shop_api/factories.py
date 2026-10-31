"""Test data factories: unique where it must be unique, reproducible where it can be."""

from __future__ import annotations

import uuid

from faker import Faker

TEST_PASSWORD = "Qa-test-password-1"  # noqa: S105 - test-only value for customers the tests create


def suffix() -> str:
    return uuid.uuid4().hex[:8]


def unique_email(prefix: str = "qa-py") -> str:
    return f"{prefix}-{suffix()}@example.com"


def unique_code(prefix: str = "QAPY") -> str:
    return f"{prefix}-{suffix().upper()}"


def seeded_faker(seed_text: str) -> Faker:
    faker = Faker("en_US")
    faker.seed_instance(seed_text)
    return faker


def address(faker: Faker, country_code: str = "dk") -> dict[str, str]:
    return {
        "first_name": faker.first_name(),
        "last_name": faker.last_name(),
        "address_1": faker.street_address(),
        "city": faker.city(),
        "postal_code": faker.numerify("####"),
        "country_code": country_code,
    }
