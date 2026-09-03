"""bge-m3 嵌入封装（仅 dense 向量，dim=1024）。

GPU 占用：依赖环境变量 CUDA_VISIBLE_DEVICES，调用方在服务器上设为 4,5,6,7，
与生产 Ollama(GPU 0-3) 物理隔离，互不干扰——本模块不主动选卡，只消费外层给定的可见设备。

torch / sentence_transformers 均为「懒加载」：import 本模块不需要这些重量级依赖，
便于在无 GPU 的本地机器上做语法/导入校验。
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_MODEL_NAME = "BAAI/bge-m3"
_DIM = 1024
_model = None  # 懒加载单例


def get_dim() -> int:
    return _DIM


def _pick_device() -> str:
    """优先用 CUDA_VISIBLE_DEVICES 视角下的 GPU，否则退回 CPU。"""
    import torch  # 懒加载

    if torch.cuda.is_available():
        # 在 CUDA_VISIBLE_DEVICES=4,5,6,7 下，cuda:0 即物理 GPU4，依次类推
        return "cuda:0"
    logger.warning("未检测到 CUDA，回退 CPU（嵌入会非常慢，仅用于本地校验）")
    return "cpu"


def _load_model(model_name: str | None = None):
    global _model
    if _model is not None:
        return _model
    name = model_name or os.getenv("EMBED_MODEL", _MODEL_NAME)
    logger.info("加载嵌入模型 %s ...", name)
    from sentence_transformers import SentenceTransformer  # 懒加载

    _model = SentenceTransformer(name, device=_pick_device())
    return _model


def embed(texts, model_name: str | None = None, batch_size: int = 32) -> list[list[float]]:
    """批量编码，返回 L2/余弦归一化后的 dense 向量列表（IP 可用）。"""
    if isinstance(texts, str):
        texts = [texts]
    model = _load_model(model_name)
    vecs = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vecs.tolist()
