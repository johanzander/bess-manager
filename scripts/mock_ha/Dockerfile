FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --root-user-action=ignore --disable-pip-version-check \
    -r requirements.txt

COPY . .

EXPOSE 8123

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8123"]
