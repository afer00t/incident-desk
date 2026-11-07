FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py clocked.py fixtures.py ./
COPY static ./static
RUN mkdir -p data && chmod 777 data

ENV CLOCKED_API_KEY=
EXPOSE 8777
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8777"]