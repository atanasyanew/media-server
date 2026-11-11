FROM python:3.13-alpine
WORKDIR /app
COPY app.py index.html /app/
USER 65534:65534
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/healthz', timeout=3)"
CMD ["python", "app.py"]
