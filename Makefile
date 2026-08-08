.PHONY: help test test-python test-java test-fast corpus equivalence golden docs clean tools

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest
MVN    ?= mvn

help:
	@echo "make test         run every characterization suite (needs cobc, perl+DBD::SQLite, docker, JDK 17)"
	@echo "make test-python  COBOL, Perl, SQL, JCL, corpus and equivalence suites"
	@echo "make test-java    the web-tier suite"
	@echo "make test-fast    skip the suites marked slow"
	@echo "make corpus       regenerate tests/corpus from build_corpus.py"
	@echo "make equivalence  print the cross-engine equivalence report"
	@echo "make golden       rewrite every golden file (review the diff!)"

test: test-python test-java

test-python:
	$(PYTEST) tests -v

test-java:
	cd java && $(MVN) -B test

test-fast:
	$(PYTEST) tests -m "not slow" -q

corpus:
	$(PYTHON) tests/corpus/build_corpus.py

equivalence:
	cd tests && $(PYTHON) -m harness.equivalence

golden: corpus
	UPDATE_GOLDEN=1 $(PYTEST) tests -q
	cd java && $(MVN) -B test -Dgolden.update=true

clean:
	rm -rf java/target .pytest_cache tests/**/__pycache__

tools:
	@echo "Ubuntu:"
	@echo "  sudo apt-get install -y gnucobol libdbd-sqlite3-perl openjdk-17-jdk maven"
	@echo "  docker is needed for the SQL suite (postgres:16-alpine)"

docs:
	cd tests && $(PYTHON) -m harness.equivalence --write-doc
