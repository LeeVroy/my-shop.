"""Self-funding store bot v2. Runs once a day. Dies if it stops earning.

All settings live in config.json. The only secret is GEMINI_API_KEY (env var / GitHub secret).
Daily: check income -> update runway -> (maybe) make a new product -> write a blog post -> rebuild site in docs/.
"""
import datetime, html, json, os, re, secrets, sys, urllib.request

USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
LEDGER = "ledger.json"
CFG = json.load(open("config.json"))


# ---------- helpers ----------
def load():
    if os.path.exists(LEDGER):
        return json.load(open(LEDGER))
    return {"runway": float(CFG["start_runway_days"]), "seen_tx": [], "earned_total": 0.0,
            "dead": False, "log": [], "products": [], "posts": []}


def save(l):
    json.dump(l, open(LEDGER, "w"), indent=2)


def http_json(url, data=None):
    req = urllib.request.Request(url, data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def ask(prompt, as_json=False):
    if os.getenv("DRY_RUN"):
        if as_json:
            return json.dumps({"niche": "test niche", "title": "Test Starter Pack",
                               "tagline": "A test product.", "content": "# Test\n\n- one\n- two\n\nBody **text**."})
        return "# Test post\n\nHello world.\n\n- a\n- b"
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           f"{CFG['model']}:generateContent?key={os.environ['GEMINI_API_KEY']}")
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    if as_json:
        body["generationConfig"] = {"responseMimeType": "application/json"}
    return http_json(url, body)["candidates"][0]["content"]["parts"][0]["text"]


def new_income(l):
    """Read-only blockchain check of your deposit address (cannot move money)."""
    addr = CFG["usdt_address"]
    if addr.startswith("PASTE"):
        return 0.0
    url = (f"https://api.trongrid.io/v1/accounts/{addr}/transactions/trc20"
           f"?only_to=true&limit=200&contract_address={USDT_TRC20}")
    total = 0.0
    try:
        for tx in http_json(url).get("data", []):
            if tx["transaction_id"] in l["seen_tx"]:
                continue
            l["seen_tx"].append(tx["transaction_id"])
            total += int(tx["value"]) / 10 ** int(tx["token_info"]["decimals"])
    except Exception as e:
        print("payment check failed:", e)
    return total


# ---------- tiny markdown -> html ----------
def inline(t):
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(t))


def md(text):
    out, in_list = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("- ", "* ")):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(s[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"(#{1,3})\s+(.*)", s)
        if m:
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif s:
            out.append(f"<p>{inline(s)}</p>")
    if in_list:
        out.append("</ul>")
    return "\n".join(out)


def page(title, body, root=""):
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font-family:system-ui,sans-serif;max-width:680px;margin:0 auto;padding:16px;line-height:1.6}}
a{{color:#0a58ca}}code,input{{word-break:break-all}}input{{width:100%;padding:8px;margin:6px 0}}
button{{padding:10px 16px}}.box{{border:1px solid #ccc;border-radius:8px;padding:12px;margin:16px 0}}</style></head>
<body><p><a href="{root}index.html">{html.escape(CFG['site_name'])}</a></p>{body}</body></html>"""


# ---------- site ----------
def build_site(l):
    os.makedirs("docs/posts", exist_ok=True)
    if l["dead"]:
        open("docs/index.html", "w").write(page(CFG["site_name"], "<h1>Closed</h1><p>This store has closed.</p>"))
        return
    prod = l["products"][-1] if l["products"] else None
    cfg_js = json.dumps({"addr": CFG["usdt_address"], "usdt": USDT_TRC20, "price": CFG["price_usd"],
                         "link": prod["path"] if prod else ""}).replace("</", "<\\/")
    buy = ""
    if prod:
        payoneer = (f'<p>Pay by card instead: <a href="{html.escape(CFG["payoneer_link"])}">pay link</a></p>'
                    if CFG.get("payoneer_link") else "")
        buy = f"""<h1>{html.escape(prod['title'])}</h1><p>{html.escape(prod['tagline'])}</p>
<div class="box"><b>Price: ${CFG['price_usd']} USDT (TRC20 network only)</b>
<p>1. Send at least {CFG['price_usd']} USDT on the <b>TRC20</b> network to:</p><code>{html.escape(CFG['usdt_address'])}</code>
<p>2. Paste your transaction ID (TXID) here and press the button:</p>
<input id="tx" placeholder="Transaction ID"><button onclick="verify()">Verify and download</button>
<p id="msg"></p>{payoneer}</div>
<script>const C={cfg_js};
async function verify(){{const tx=document.getElementById('tx').value.trim(),m=document.getElementById('msg');
m.textContent='Checking...';try{{const r=await fetch(`https://api.trongrid.io/v1/accounts/${{C.addr}}/transactions/trc20?only_to=true&limit=200&contract_address=${{C.usdt}}`);
const j=await r.json();const t=(j.data||[]).find(x=>x.transaction_id===tx);
if(!t){{m.textContent='Payment not found yet. Wait 2 minutes after sending and try again.';return}}
const a=Number(t.value)/10**Number(t.token_info.decimals);
if(a<C.price){{m.textContent='Amount received was too low.';return}}
m.innerHTML='Payment confirmed. <a href="'+C.link+'">Download your product</a>'}}catch(e){{m.textContent='Could not check. Try again.'}}}}</script>"""
    posts = "".join(f'<li><a href="posts/{p["date"]}.html">{html.escape(p["title"])}</a></li>'
                    for p in reversed(l["posts"][-30:]))
    open("docs/index.html", "w").write(page(CFG["site_name"], buy + f"<h2>Articles</h2><ul>{posts}</ul>"))


def make_product(l):
    past = ", ".join(p["niche"] for p in l["products"]) or "none"
    raw = ask("You run a zero-budget digital-product shop. Choose ONE niche with real search demand "
              f"where a short paid guide or checklist pack is useful. Already tried: {past}. Pick a different one. "
              "Reply as JSON with keys: niche, title, tagline (one sentence), content (a genuinely useful "
              "~1200-word guide in markdown). No income claims, no fake reviews.", as_json=True)
    d = json.loads(raw)
    token = secrets.token_urlsafe(12)
    os.makedirs(f"docs/dl/{token}", exist_ok=True)
    open(f"docs/dl/{token}/index.html", "w").write(page(d["title"], md(d["content"])))
    l["products"].append({"niche": d["niche"], "title": d["title"], "tagline": d["tagline"],
                          "path": f"dl/{token}/index.html", "created": datetime.date.today().isoformat(),
                          "earned_at_creation": l["earned_total"]})


def make_post(l, today):
    prod = l["products"][-1]
    os.makedirs("docs/posts", exist_ok=True)
    text = ask(f"Write a useful, honest 400-word blog post in markdown for people interested in: {prod['niche']}. "
               "Start with a '# ' title line. Give real tips. Do not make income claims or fake testimonials.")
    first = text.strip().splitlines()[0].lstrip("# ").strip() if text.strip() else today
    body = md(text) + f'<div class="box">Want the full guide? <a href="../index.html">Get {html.escape(prod["title"])}</a></div>'
    open(f"docs/posts/{today}.html", "w").write(page(first, body, root="../"))
    l["posts"].append({"date": today, "title": first})


# ---------- main ----------
def main():
    l = load()
    if l["dead"]:
        print("Bot is dead. Delete ledger.json to revive it.")
        return
    today = datetime.date.today().isoformat()
    if l["log"] and l["log"][-1]["date"] == today:
        print("Already ran today.")
        return

    earned = new_income(l)
    l["earned_total"] += earned
    l["runway"] += earned * CFG["days_added_per_dollar"] if earned > 0 else -1
    l["log"].append({"date": today, "earned_usd": round(earned, 2), "runway": round(l["runway"], 1)})

    if l["runway"] <= 0:
        l["dead"] = True
        build_site(l)
        save(l)
        print("Runway reached zero. The bot has died.")
        return

    try:
        stale = l["products"] and (datetime.date.today() - datetime.date.fromisoformat(l["products"][-1]["created"])).days >= 14 \
            and l["earned_total"] == l["products"][-1]["earned_at_creation"]
        if not l["products"] or stale:
            make_product(l)
        make_post(l, today)
    except Exception as e:
        print("AI step failed:", e)

    build_site(l)
    save(l)
    print(f"Done. Earned ${earned:.2f} today. Runway {l['runway']:.1f} days.")


if __name__ == "__main__":
    main()
