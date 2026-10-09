# syntax=docker/dockerfile:1
# ---------------------------------------------------------------- 阶段 1：前端构建
FROM node:20-alpine AS frontend
ARG NPM_REGISTRY=https://registry.npmmirror.com
RUN npm config set registry "$NPM_REGISTRY"
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- 阶段 2：运行时
FROM python:3.12-slim
ARG UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_INDEX_URL=$UV_INDEX_URL \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 依赖单独一层：pyproject 不变时可复用构建缓存
# 注：直接用 pip 安装（不再依赖 uv，部分镜像源会拒发 uv 的 wheel），并剔掉 requirements 里的注释与空行
COPY pyproject.toml ./
RUN python -c "import tomllib; print('\n'.join(x for x in tomllib.load(open('pyproject.toml','rb'))['project']['dependencies'] if x.strip() and not x.strip().startswith('#')))" > /tmp/req.txt \
 && pip install --no-cache-dir -r /tmp/req.txt \
 && rm /tmp/req.txt

COPY . .
COPY --from=frontend /build/dist ./frontend/dist

# 运行期目录先建好并交给非 root 用户：named volume 首次挂载会继承这里的属主
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app \
 && mkdir -p /app/data /app/workspace /app/runtime_logs \
 && chown -R app:app /app

USER app

EXPOSE 8003
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8003/api/health', timeout=5)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
