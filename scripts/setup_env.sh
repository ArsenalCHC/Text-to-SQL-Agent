#!/usr/bin/env bash
# =====================================================================
# 部署环境变量集中配置（在服务器上 source 一次，后续命令自动继承）
#
# 用法：
#   source scripts/setup_env.sh
#
# 说明：
#   - CUDA_VISIBLE_DEVICES 限定 GPU 4-7 空闲卡，绝不碰生产 Ollama(GPU0-3)
#   - EMBED_MODEL 指向服务器已有的 bge-m3 本地缓存，避免联网下载 2.2G
#   - Milvus 默认本机 19555，跨机时取消注释改 IP
# =====================================================================

# 1) GPU 隔离：只用 4-7 空闲卡
export CUDA_VISIBLE_DEVICES=4,5,6,7

# 2) bge-m3 本地路径（改成你的实际缓存路径）
export EMBED_MODEL=/path/to/modelscope/bge-m3

# 3) Milvus 连接（默认本机 19555；跨机部署时取消注释并改 IP）
# export MILVUS_HOST=127.0.0.1
# export MILVUS_PORT=19555

# 4) ClickHouse（生产 DWD 库；backend=clickhouse 时生效，覆盖 config/clickhouse.yaml）
# export CLICKHOUSE_HOST=10.x.x.x
# export CLICKHOUSE_PORT=8123
# export CLICKHOUSE_USER=default
# export CLICKHOUSE_PASSWORD=你的密码
# export CLICKHOUSE_DB=text2sql

echo "[setup_env] CUDA_VISIBLE_DEVICES = $CUDA_VISIBLE_DEVICES"
echo "[setup_env] EMBED_MODEL          = $EMBED_MODEL"
echo "[setup_env] 环境变量已就绪，后续命令自动继承"
