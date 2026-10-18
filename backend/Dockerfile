FROM python:3.11-slim

WORKDIR /app

# --- Heavy, rarely-changing layers FIRST, so editing code never re-downloads them ---
# CPU-only PyTorch. The default wheel drags in gigabytes of CUDA libraries.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
# torch is already satisfied, so pip keeps the CPU build.
RUN pip install --no-cache-dir sentence-transformers

# Bake the model into the image so containers start with no network (see ADR-07).
ARG EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import SentenceTransformer as S; S('${EMBEDDING_MODEL}')" \
 && chmod -R a+rX /opt/hf
# AFTER the download (setting this earlier would block it)
ENV HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false

# --- The project itself ---
COPY . .
RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
