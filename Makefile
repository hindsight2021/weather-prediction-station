.PHONY: install test compile qa verify docker-build

install:
	python -m pip install --upgrade pip
	pip install -r requirements.txt

test:
	pytest -q

compile:
	python -m compileall app training calibration inference verification tests

qa: compile test

verify:
	python -m verification.report

docker-build:
	docker compose build
