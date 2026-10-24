"""Jackson AI PDF Cleaner - web service (FastAPI).
POST /clean      (multipart: file=<pdf>, options=<json string>)  -> {"job": id}
GET  /job/{id}   -> {"status": "queued|running|done|error", "log": [...], "result": {...}}
GET  /download/{id}  -> the cleaned PDF
GET  /           -> health check
"""
import os, json, uuid, threading, tempfile, time, shutil
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import clean

ALLOWED = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "https://jacksonhabimana.github.io").split(",") if o.strip()]
MAX_MB = int(os.environ.get("MAX_UPLOAD_MB", "150"))
WORK = tempfile.mkdtemp(prefix="pdfclean_")
JOBS = {}
LOCK = threading.Semaphore(1)       # one book at a time keeps the free server from running out of memory

app = FastAPI(title="Jackson AI PDF Cleaner")
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED, allow_methods=["*"], allow_headers=["*"])


def run(job_id, src, dst, opts):
    j = JOBS[job_id]
    with LOCK:
        j["status"] = "running"
        try:
            j["result"] = clean.clean_pdf(src, dst, opts, progress=lambda m: j["log"].append(str(m)))
            j["status"] = "done"
        except Exception as e:          # report the problem to the page instead of crashing
            j["status"] = "error"
            j["log"].append("Error: " + str(e))
        finally:
            try: os.remove(src)
            except OSError: pass


def sweep():
    now = time.time()
    for k in [k for k, v in JOBS.items() if now - v["t"] > 3600]:
        shutil.rmtree(os.path.join(WORK, k), ignore_errors=True)
        JOBS.pop(k, None)


@app.get("/")
def health():
    return {"ok": True, "service": "Jackson AI PDF Cleaner"}


@app.post("/clean")
async def start(file: UploadFile = File(...), options: str = Form("{}")):
    sweep()
    try:
        opts = json.loads(options or "{}")
        assert isinstance(opts, dict)
    except Exception:
        raise HTTPException(400, "options must be a JSON object")
    jid = uuid.uuid4().hex[:12]
    d = os.path.join(WORK, jid); os.makedirs(d)
    src, dst = os.path.join(d, "in.pdf"), os.path.join(d, "out.pdf")
    size = 0
    with open(src, "wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_MB << 20:
                raise HTTPException(413, f"File is larger than {MAX_MB} MB")
            f.write(chunk)
    if not open(src, "rb").read(5).startswith(b"%PDF"):
        raise HTTPException(400, "That file is not a PDF")
    name = os.path.splitext(file.filename or "book")[0]
    JOBS[jid] = dict(status="queued", log=[], result=None, t=time.time(), out=dst, name=name)
    threading.Thread(target=run, args=(jid, src, dst, opts), daemon=True).start()
    return {"job": jid}


@app.get("/job/{jid}")
def job(jid: str):
    j = JOBS.get(jid)
    if not j: raise HTTPException(404, "Unknown job")
    return {k: j[k] for k in ("status", "log", "result")}


@app.get("/download/{jid}")
def download(jid: str):
    j = JOBS.get(jid)
    if not j or j["status"] != "done": raise HTTPException(404, "Not ready")
    return FileResponse(j["out"], media_type="application/pdf", filename=j["name"] + "_cleaned.pdf")
