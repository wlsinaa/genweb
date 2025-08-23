FROM python:3.11-slim
WORKDIR /app
# Install build tools and upgrade pip
RUN pip install --no-cache-dir --upgrade pip
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Verify key dependencies
RUN pip show streamlit google-cloud-storage uvicorn || { echo "Dependency not installed"; exit 1; }
COPY src/ src/
COPY .streamlit/ .streamlit/
ENV PORT=8000
EXPOSE 8000
CMD ["streamlit", "run", "src/main.py", "--server.port", "8000", "--server.address", "0.0.0.0"]