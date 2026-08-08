import shutil
import sys
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))
# The Python replacements live outside the test tree and are imported by name.
sys.path.insert(1, str(TESTS_DIR.parent / "python"))

from harness.engines import cobol, postgres  # noqa: E402
from harness.model import load_corpus  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "cobol: needs GnuCOBOL")
    config.addinivalue_line("markers", "docker: needs Docker (PostgreSQL container)")
    config.addinivalue_line("markers", "perl: needs perl with DBD::SQLite")
    config.addinivalue_line("markers", "slow: takes more than a few seconds")


REQUIRED_TOOLS = {"cobol": "cobc", "perl": "perl", "docker": "docker"}


def pytest_runtest_setup(item):
    """Skip a suite whose engine is not installed rather than failing it."""
    for marker in item.iter_markers():
        tool = REQUIRED_TOOLS.get(marker.name)
        if tool and not shutil.which(tool):
            pytest.skip(f"{tool} is not installed; see docs/testing.md")


@pytest.fixture(scope="session")
def corpus():
    return load_corpus()


@pytest.fixture(scope="session")
def cobol_run(corpus, tmp_path_factory):
    """Single patched batch run shared by the COBOL tests."""
    rows, report = cobol.run(corpus, tmp_path_factory.mktemp("cobol"))
    return rows, report


@pytest.fixture(scope="session")
def cobol_rows(cobol_run):
    return cobol_run[0]


@pytest.fixture(scope="session")
def pg_database():
    with postgres.database() as container:
        yield container


@pytest.fixture(scope="session")
def sql_rows(pg_database, corpus):
    postgres.load_corpus(pg_database, corpus)
    return postgres.run_extract(pg_database, corpus)
