# Offline Evaluation

`run_evaluation.py` 使用 datasets 中的人工可解释案例重新计算指标，不调用网络或 LLM。Retrieval baseline 是最小词法匹配；由于没有历史版本，A0/A1/A2 不伪造比较，结果会标明 unavailable。
