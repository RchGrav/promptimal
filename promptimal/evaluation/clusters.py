from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, Dict, List


def response_clusters(executions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    clusters = OrderedDict()
    for execution in executions:
        normalized = execution.get("evaluation", {}).get("normalized_output")
        if execution.get("response", {}).get("status") != "ok" or normalized is None:
            continue
        key = json.dumps(normalized, ensure_ascii=False, sort_keys=True)
        if key not in clusters:
            clusters[key] = {
                "normalized_output": normalized,
                "execution_ids": [],
                "count": 0,
            }
        clusters[key]["execution_ids"].append(execution["id"])
        clusters[key]["count"] += 1
    total = sum(item["count"] for item in clusters.values())
    for cluster in clusters.values():
        cluster["share"] = cluster["count"] / total if total else None
    return sorted(clusters.values(), key=lambda item: -item["count"])
