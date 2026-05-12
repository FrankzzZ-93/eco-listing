import datetime
import json
import os


class MemoryHelper:
    @staticmethod
    def has(state: dict, key: str) -> bool:
        val = state.get(key)
        if val is None:
            return False
        if isinstance(val, (list, dict, str)) and len(val) == 0:
            return False
        return True

    @staticmethod
    def log_action(agent: str, action: str, **kwargs) -> dict:
        return {
            "agent": agent,
            "action": action,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            **kwargs,
        }

    @staticmethod
    def save_snapshot(state: dict, artifacts_dir: str) -> str:
        run_dir = os.path.join(artifacts_dir, state["run_id"])
        os.makedirs(run_dir, exist_ok=True)
        path = os.path.join(run_dir, "memory_snapshot.json")
        serializable = {k: v for k, v in state.items()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)
        return path
