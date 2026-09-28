from pathlib import Path

import pytest

from sponsor_check.register import Register, build_database

FIXTURE = Path(__file__).parent / "fixtures" / "register_sample.csv"


@pytest.fixture(scope="session")
def register(tmp_path_factory) -> Register:
    db = tmp_path_factory.mktemp("db") / "register.sqlite3"
    build_database(
        FIXTURE, db,
        source_url="https://assets.publishing.service.gov.uk/media/x/"
                   "SP_-_Worker_and_Temporary_Worker_Web_Register_-_2026-09-28.csv",
    )
    return Register(db)
