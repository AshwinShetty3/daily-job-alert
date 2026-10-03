"""Internal n8n adapters; same tested Python filters and durable state."""
import hmac
import json
import os
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import job_alerts as a

CONFIG = json.loads((a.ROOT / "config.json").read_text())
SOURCES = {"remotive": a.remotive, "remoteok": a.remoteok, "himalayas": a.himalayas, "wwr": a.wwr, "adzuna": a.adzuna, "jsearch": a.jsearch}


def state():
    return json.loads((a.ROOT / "data/state.json").read_text())


def operation(path, payload):
    now = datetime.now(a.UTC)
    if path == "/filter":
        # Metadata sentinel keeps the pipeline alive even with zero matching jobs.
        items = []
        for index, part in enumerate(payload["sources"]):
            items.append({"kind": "metadata", "eligible": True, "dedupe_key": f"metadata-{index}", "warnings": part.get("warnings", []), "message_ids": part.get("message_ids", [])})
            for row in part.get("jobs", []):
                job = a.Job(**row)
                allowed = a.eligible(job, now)
                items.append({"kind": "job", "eligible": allowed, "dedupe_key": job.ids()[0], "job": a.asdict(job)})
        return {"items": items}
    if path.startswith("/source/"):
        name = path.rsplit("/", 1)[-1]
        try:
            if name == "gmail":
                jobs, ids, _, warnings = a.gmail(CONFIG, state(), now)
                return {"jobs": [a.asdict(j) for j in jobs], "message_ids": ids, "warnings": warnings}
            result = SOURCES[name](CONFIG, state(), now)
            jobs, warnings = result if isinstance(result, tuple) else (result, [])
            return {"jobs": [a.asdict(j) for j in jobs], "warnings": warnings, "message_ids": []}
        except Exception as error:
            return {"jobs": [], "message_ids": [], "warnings": [f"{name} failed ({type(error).__name__}); coverage incomplete"]}
    if path == "/prepare":
        current = state()
        jobs, batch, warnings, ids = [], set(), [], []
        for part in payload["sources"]:
            warnings.extend(part.get("warnings", []))
            ids.extend(part.get("message_ids", []))
            for row in part.get("jobs", []):
                job = a.Job(**row)
                if a.eligible(job, now) and not any(k in current["seen"] or k in batch for k in job.ids()):
                    jobs.append(job)
                    batch.update(job.ids())
        token = uuid.uuid4().hex
        pending = a.ROOT / "data/pending"
        pending.mkdir(exist_ok=True)
        (pending / (token + ".json")).write_text(json.dumps({"keys": list(batch), "message_ids": list(set(ids)), "created": now.isoformat()}))
        return {"token": token, "jobs": [a.asdict(j) for j in jobs], "html": a.digest(jobs, list(dict.fromkeys(warnings)), now), "count": len(jobs), "warnings": list(dict.fromkeys(warnings))}
    if path == "/commit":
        token = payload["token"]
        if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
            raise ValueError("Invalid token")
        pending = a.ROOT / "data/pending" / (token + ".json")
        if not pending.exists():
            return {"committed": True, "already_committed": True}
        value = json.loads(pending.read_text())
        current = state()
        current["seen"].update({k: now.isoformat() for k in value["keys"]})
        current["processed_messages"] = list(set(current.get("processed_messages", [])) | {a.message_key(mid) for mid in value["message_ids"]})
        a.save_state(current)
        if value["message_ids"]:
            a.mark_processed(a.gmail_service(), value["message_ids"], CONFIG)
        pending.unlink()
        return {"committed": True}
    raise ValueError("Unknown endpoint")


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        secret = os.environ.get("WORKER_SECRET", "")
        if not secret or not hmac.compare_digest(self.headers.get("X-Worker-Secret", ""), secret):
            self.send_error(403)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 20_000_000:
                raise ValueError("Request too large")
            payload = json.loads(self.rfile.read(size) or b"{}")
            body = json.dumps(operation(self.path, payload)).encode()
            self.send_response(200)
        except Exception as error:
            body = json.dumps({"error": type(error).__name__}).encode()
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    if not os.getenv("WORKER_SECRET"):
        raise RuntimeError("WORKER_SECRET is required")
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
