# 智能问数系统 Dockerfile（API + UI 共用镜像）

FROM python:3.11-slim

WORKDIR /app

# 先装轻量依赖；torch/sentence-transformers 体积大，GPU 版在服务器上按需装
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt \
    && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple fastapi "uvicorn[standard]" streamlit

COPY . .

EXPOSE 8000 8501
CMD ["python", "scripts/run_api.py"]
