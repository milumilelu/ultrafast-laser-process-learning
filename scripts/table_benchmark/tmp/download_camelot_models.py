import os, sys, time
from huggingface_hub import snapshot_download

MODELS = [
    "microsoft/table-transformer-detection",
    "microsoft/table-transformer-structure-recognition-v1.1-all",
]

def incomplete(path):
    n = 0
    for root, _, files in os.walk(path):
        for f in files:
            if f.endswith(".incomplete"):
                n += 1
    return n

def attempt(model, endpoint):
    if endpoint:
        os.environ["HF_ENDPOINT"] = endpoint
    else:
        os.environ.pop("HF_ENDPOINT", None)
    print(f"[{time.strftime('%H:%M:%S')}] downloading {model} via {endpoint or 'huggingface.co'} ...", flush=True)
    p = snapshot_download(model, max_workers=1, resume_download=True)
    return p

for model in MODELS:
    ok = False
    for attempt_no in range(30):
        for endpoint in [None, "https://hf-mirror.com"]:
            try:
                p = attempt(model, endpoint)
                if incomplete(p) == 0:
                    print(f"OK {model} -> {p}", flush=True)
                    ok = True
                    break
                else:
                    print(f"incomplete files remain: {incomplete(p)}", flush=True)
            except Exception as e:
                print(f"attempt failed ({endpoint}): {type(e).__name__}: {e}", flush=True)
            time.sleep(2)
        if ok:
            break
        print(f"retry loop {attempt_no+1} for {model}", flush=True)
    if not ok:
        print(f"FAILED to download {model}", flush=True)
        sys.exit(1)
print("ALL MODELS OK", flush=True)
