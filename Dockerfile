FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer cached unless requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Initialise database if it doesn't exist
RUN python scripts/init_db.py

EXPOSE 8050

ENV PYTHONUNBUFFERED=1

CMD ["python", "dashboard/app.py"]
