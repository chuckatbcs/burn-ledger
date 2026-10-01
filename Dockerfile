FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
RUN mkdir -p /data
ENV BURN_LEDGER_DB=/data/burn-ledger.db
EXPOSE 8795
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8795"]
