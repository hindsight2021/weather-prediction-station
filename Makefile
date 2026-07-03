.PHONY: install test compile qa docker-build

install:
	python -m pip install --upgrade pip
	pip install -r requirements.txt

test:
	pytest -q

compile:
	python -m compileall app training calibration inference tests

qa: compile test

docker-build:
	docker compose build
