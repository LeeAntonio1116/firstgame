# [S10] Google Cloud Run 배포용 — python:3.12-slim 단일 스테이지.
# (BuildKit `# syntax` 지시어 미사용: Cloud Build에서 provenance attestation이 붙은
#  OCI 멀티-manifest가 생성되면 Cloud Run "Container import failed"가 나기 때문.
#  legacy docker 빌드로 단일 manifest 이미지를 만든다.)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 의존성 레이어 분리 — requirements가 안 바뀌면 빌드 캐시 재사용(빌드·cold start 가속)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Cloud Run이 $PORT(기본 8080)를 주입. uvicorn 워커 1개 — 인메모리 rate limit/OTP 상태 일관성.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 1
