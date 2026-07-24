"""VPN impact test - full prompt phase."""
import asyncio, json, base64, time, sys, os, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

IMG_PATH = Path(r"C:\Users\97020\AppData\Roaming\Qoder\SharedClientCache\cache\images\task-375\e0057364f7cf1f3bc8f811da7fde1606-761bb10d.jpg")

def get_prompt():
    import yaml
    sp = Path(__file__).resolve().parent.parent / "config" / "record_schema.yaml"
    with open(sp, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return f"{cfg.get('system_prompt','')}\n\n{cfg.get('instructions','')}"

async def run_httpx_full(attempt, trust_env, prompt, img_bytes):
    import httpx
    api_key = os.environ["QWEN_TEST_API_KEY"]
    url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    mime = "image/jpeg"
    b64 = base64.b64encode(img_bytes).decode()
    body = {"model":"qwen3.7-plus","temperature":0,"response_format":{"type":"json_object"},
            "enable_thinking":False,"messages":[{"role":"user","content":[
            {"type":"image_url","image_url":{"url":f"data:{mime};base64,{b64}"}},
            {"type":"text","text":prompt}]}]}
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=60.0, pool=30.0)
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=trust_env, http2=False) as c:
            resp = await c.post(url, headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}, json=body)
            ms = (time.perf_counter()-t0)*1000
            rj = resp.json()
            content = ""
            if rj.get("choices"):
                content = rj["choices"][0].get("message",{}).get("content","")
            valid_json = False
            try:
                json.loads(content)
                valid_json = True
            except: pass
            return {"attempt":attempt,"trust_env":trust_env,"latency_ms":round(ms),
                    "status":resp.status_code,"got_content":bool(content),
                    "content_chars":len(content),"valid_json":valid_json,
                    "request_id":resp.headers.get("x-request-id","") or rj.get("request_id",""),
                    "server":resp.headers.get("server",""),"error":None,
                    "fail_30_50": 30000<ms<50000 and resp.status_code!=200,
                    "success_60_120": 60000<ms<120000 and resp.status_code==200}
    except Exception as e:
        ms = (time.perf_counter()-t0)*1000
        return {"attempt":attempt,"trust_env":trust_env,"latency_ms":round(ms),
                "status":None,"got_content":False,"content_chars":0,"valid_json":False,
                "request_id":"","server":"","error":f"{type(e).__name__}:{repr(e)[:150]}",
                "fail_30_50": 30000<ms<50000,
                "success_60_120": False}

async def run_openai_full(attempt, prompt, img_bytes):
    api_key = os.environ["QWEN_TEST_API_KEY"]
    b64 = base64.b64encode(img_bytes).decode()
    data_url = f"data:image/jpeg;base64,{b64}"
    t0 = time.perf_counter()
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
        resp = await client.chat.completions.create(
            model="qwen3.7-plus", temperature=0,
            response_format={"type":"json_object"},
            extra_body={"enable_thinking":False},
            messages=[{"role":"user","content":[
                {"type":"image_url","image_url":{"url":data_url}},
                {"type":"text","text":prompt}]}])
        ms = (time.perf_counter()-t0)*1000
        content = resp.choices[0].message.content if resp.choices else ""
        valid_json = False
        try:
            json.loads(content)
            valid_json = True
        except: pass
        return {"attempt":attempt,"client":"openai_sdk","latency_ms":round(ms),
                "status":200,"got_content":bool(content),"content_chars":len(content),
                "valid_json":valid_json,"request_id":getattr(resp,"request_id","") or "",
                "error":None,"fail_30_50":False,"success_60_120":60000<ms<120000}
    except Exception as e:
        ms = (time.perf_counter()-t0)*1000
        return {"attempt":attempt,"client":"openai_sdk","latency_ms":round(ms),
                "status":None,"got_content":False,"content_chars":0,"valid_json":False,
                "request_id":"","error":f"{type(e).__name__}:{repr(e)[:150]}",
                "fail_30_50":30000<ms<50000,"success_60_120":False}

async def main():
    prompt = get_prompt()
    img_bytes = IMG_PATH.read_bytes()
    print(f"Image: {len(img_bytes)} bytes, Prompt: {len(prompt)} chars")
    results = []

    # A5: httpx trust_env=True full prompt x3
    print("\n[A5] httpx trust_env=True full prompt ...")
    for i in range(1,4):
        r = await run_httpx_full(i, True, prompt, img_bytes)
        s = "OK" if r.get("status")==200 and r["got_content"] else f"FAIL:{r.get('error','no content')}"
        print(f"  #{i}: {r['latency_ms']}ms {s} chars={r['content_chars']}")
        results.append({**r, "test_id":"A5", "client":"httpx"})

    # A6: httpx trust_env=False full prompt x3
    print("\n[A6] httpx trust_env=False full prompt ...")
    for i in range(1,4):
        r = await run_httpx_full(i, False, prompt, img_bytes)
        s = "OK" if r.get("status")==200 and r["got_content"] else f"FAIL:{r.get('error','no content')}"
        print(f"  #{i}: {r['latency_ms']}ms {s} chars={r['content_chars']}")
        results.append({**r, "test_id":"A6", "client":"httpx"})

    # A7: OpenAI SDK full prompt x3
    print("\n[A7] OpenAI SDK full prompt ...")
    for i in range(1,4):
        r = await run_openai_full(i, prompt, img_bytes)
        s = "OK" if r.get("status")==200 and r["got_content"] else f"FAIL:{r.get('error','no content')}"
        print(f"  #{i}: {r['latency_ms']}ms {s} chars={r['content_chars']}")
        results.append({**r, "test_id":"A7"})

    # Save
    out_dir = Path(__file__).resolve().parent.parent / "data" / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"vpn_fullprompt_A_{ts}.json"
    out.write_text(json.dumps({"vpn_state":"on","results":results}, indent=2, ensure_ascii=False), encoding="utf-8")
    
    succ = sum(1 for r in results if r.get("status")==200 and r["got_content"])
    print(f"\n=== VPN ON Full Prompt: {succ}/{len(results)} success ===")
    fails_30_50 = [r for r in results if r.get("fail_30_50")]
    if fails_30_50:
        print(f"  WARNING: {len(fails_30_50)} failures in 30-50s range!")
    print(f"  Saved: {out}")

asyncio.run(main())
