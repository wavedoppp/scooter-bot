FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scooter_bot.py .
CMD ["python", "scooter_bot.py"]
