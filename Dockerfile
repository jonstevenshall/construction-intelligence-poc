FROM python:3.13-slim
WORKDIR /app
COPY requirements-postgres.txt .
RUN pip install --no-cache-dir -r requirements-postgres.txt
COPY . .
RUN useradd --create-home --uid 10001 lab && mkdir -p /app/var && chown -R lab:lab /app
USER lab
EXPOSE 8765
CMD ["python", "-m", "earthworks.app", "--host", "0.0.0.0", "--port", "8765"]
