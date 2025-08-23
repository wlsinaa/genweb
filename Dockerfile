FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir --upgrade pip
RUN apt-get update && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN pip show streamlit google-cloud-storage pandas plotly regex uvicorn || { echo "Dependency not installed"; exit 1; }
COPY src/ src/
COPY .streamlit/ .streamlit/
ENV PORT=8000
EXPOSE 8000
CMD ["uvicorn", "streamlit.web.server.server:streamlit_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]