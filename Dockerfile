FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY app /app/app
COPY training /app/training
COPY calibration /app/calibration
COPY inference /app/inference

CMD ["python", "-m", "app.main"]
