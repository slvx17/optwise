# No dependencies beyond the standard library. Works on Render (Docker) and Cloud Run.
FROM python:3.12-slim
WORKDIR /app
COPY src ./src
COPY data ./data
ENV PYTHONPATH=src PYTHONUNBUFFERED=1 OPTWISE_TRUST_PROXY=1
# The host sets PORT; OPENROUTER_API_KEY comes from the host's secret settings, never the image.
CMD ["python", "-m", "optwise.web"]
