FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY priors ./priors
RUN pip install --no-cache-dir .

COPY config.yaml ./

# data/ (SQLite + artifacts), build/ and issues/ are volume-mounted in compose
CMD ["python", "-m", "priors", "daemon"]
