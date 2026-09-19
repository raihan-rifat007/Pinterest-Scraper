FROM python:3.11-slim

WORKDIR /app

COPY . .

RUN pip install -e .
RUN pip install -r requirements.txt

EXPOSE 8080

CMD ["python", "-m", "__main__", "server"]
CMD ["uvicorn", "api.server:app", "--host", "0.0.0.0", "--port", "8080"]
