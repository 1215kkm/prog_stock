FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Seoul

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src
COPY README.md ./

RUN pip install --no-cache-dir -e .

# 데이터·로그 디렉토리 (volume mount 권장)
VOLUME ["/app/data", "/app/logs"]

# 기본은 dry_run. compose에서 override.
ENV RUN_MODE=dry_run

ENTRYPOINT ["python", "-m", "prog_stock.runtime.loop"]
CMD ["--mode", "dry_run"]
