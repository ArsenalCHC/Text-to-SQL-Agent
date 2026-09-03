#!/usr/bin/env bash
# GPU 4-7 独立 Ollama 实例启动脚本（与生产 Ollama 物理隔离，零影响）
#
# 生产环境现状：
#   - 生产 Ollama：占用 GPU 0-3，监听 11434（勿动）
#   - 本实例：CUDA_VISIBLE_DEVICES=4,5,6,7，监听 11435，模型目录独立
#
# 用法：
#   bash scripts/start_ollama_isolated.sh
#   OLLAMA_MODELS=/data/ollama_t2s bash scripts/start_ollama_isolated.sh   # 自定义模型目录
set -euo pipefail

export CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-4,5,6,7}   # 只用 4 张空闲卡
export OLLAMA_HOST=${OLLAMA_HOST:-0.0.0.0:11435}              # 11435 = 独立实例端口
export OLLAMA_MODELS=${OLLAMA_MODELS:-/data/ollama_t2s}       # 独立模型目录，不污染生产模型

echo "=== 启动独立 Ollama 实例 ==="
echo "  可见 GPU    : ${CUDA_VISIBLE_DEVICES}"
echo "  监听地址    : ${OLLAMA_HOST}"
echo "  模型目录    : ${OLLAMA_MODELS}"
echo "  （生产 Ollama 在 GPU0-3 / 11434，本实例不影响它）"
echo ""
exec ollama serve
