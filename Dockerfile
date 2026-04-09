FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# The repository is mid-rename; create the import path expected by the code.
RUN ln -s /app/src/Medical_Wizard_MCP /app/src/clinical_trials_mcp

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["python", "-m", "Medical_Wizard_MCP"]
