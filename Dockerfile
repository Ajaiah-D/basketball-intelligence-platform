# Container image for the dashboard - portable across Render / Fly.io /
# Railway / any Docker host when it's time to move past Streamlit
# Community Cloud (e.g. for monetization).
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY .streamlit/ .streamlit/
COPY dashboard/ dashboard/

# The warehouse is downloaded on first boot via the WAREHOUSE_URL env var
# (see dashboard/app.py), so no data ships in the image.
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"

CMD ["python", "-m", "streamlit", "run", "dashboard/app.py", \
     "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
