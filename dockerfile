FROM python:3.13-slim AS builder 
RUN mkdir /app
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 
RUN pip install --upgrade pip
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim

COPY --from=builder /usr/local/lib/python3.13/site-packages/ /usr/local/lib/python3.13/site-packages/
COPY --from=builder /usr/local/bin/ /usr/local/bin/

WORKDIR /app

# Copy files first
COPY . .
COPY entrypoint.prod.sh /app/entrypoint.prod.sh

# Then create user, set permissions, fix line endings — all as root
RUN useradd -m -r appuser && \
    mkdir -p /app/staticfiles && \
    sed -i 's/\r//' /app/entrypoint.prod.sh && \
    chmod +x /app/entrypoint.prod.sh && \
    chown -R appuser:appuser /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1 

USER appuser
EXPOSE 8000
CMD ["/app/entrypoint.prod.sh"]