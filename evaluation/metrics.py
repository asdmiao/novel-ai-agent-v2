def hit_rates(rows):
    n=len(rows) or 1
    return {f"top{k}":sum(bool(set(r["expected"]) & set(r["retrieved"][:k])) for r in rows)/n for k in (1,3,5)}
