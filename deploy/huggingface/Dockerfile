# Hugging Face Space (Docker) for Disaster AI. This Space holds only this file and README.md: the app itself is
# downloaded from GitHub on every build, so a "Factory rebuild" after `git push` deploys the newest version.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 TZ=Asia/Kolkata
WORKDIR $HOME/app

ARG REPO=https://github.com/DhanyaHegde18/disaster-ai.git
ARG BRANCH=main
# Changes whenever a new commit is pushed, so Docker doesn't reuse an old copy of the code.
ADD https://api.github.com/repos/DhanyaHegde18/disaster-ai/commits/main /tmp/latest-commit.json
RUN git clone --depth 1 --branch "$BRANCH" "$REPO" . \
 && pip install --no-cache-dir --user -r requirements-server.txt \
 && mkdir -p backend/data

EXPOSE 7860
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
