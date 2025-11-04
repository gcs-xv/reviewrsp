from bs4 import BeautifulSoup
import re
from dateutil import parser as dtparser

# ====== format & util ======
LABEL_COL = 15
def fmt_main(label, val):   return f"{label:<{LABEL_COL}} : {val}".rstrip()
def fmt_bullet(label, val): return f"• {label:<{LABEL_COL}} : {val}".rstrip()
def fmt_head(label):        return f"• {label:<{LABEL_COL}} :"

def format_rm(rm):
    d = re.sub(r"\D","", rm or "")
    if not d: return ""
    if len(d)==6: parts=[d[:2],d[2:4],d[4:6]]
    elif len(d)==7: parts=[d[:1],d[1:3],d[3:5],d[5:7]]
    else: parts=[d[i:i+2] for i in range(0,len(d),2)]
    return ".".join([p for p in parts if p])

def format_date_ddmmyyyy(s):
    if not s: return ""
    try:
        dt = dtparser.parse(s, fuzzy=True, dayfirst=False)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return s

# ====== diagnosis & plan splitter (pintar) ======
def split_diag(ai_text: str):
    s = " ".join((ai_text or "").split())
    out = []
    m = re.search(r'(?i)\bimpaksi\b\s*([0-9]{2}(?:\s*,\s*[0-9]{2})+|[0-9]{2})', s)
    if m: out.append(f"Impaksi gigi {m.group(1).replace(' ', '')}")
    m = re.search(r'(?i)\bperikoronitis\b\s*([0-9]{2}(?:\s*,\s*[0-9]{2})+|[0-9]{2})', s)
    if m: out.append(f"Perikoronitis gigi {m.group(1).replace(' ', '')}")
    if out: return out
    # fallback (pisah koma/semicolon)
    parts = [p.strip() for p in re.split(r"[;,]\s*", s) if p.strip()]
    return [p[0].upper()+p[1:] if len(p)>1 else p.upper() for p in parts]

def split_plan(plan_text: str, instr_text: str = ""):
    t = " ; ".join([plan_text or "", instr_text or ""])
    # pecah di transisi ke "Pro ..."
    t = re.sub(r"\s+(?=Pro\s)", "\n", t, flags=re.I)
    t = t.replace("•","\n").replace("·","\n")
    t = re.sub(r"\s*[-–]\s*","\n", t)
    t = t.replace(",", "\n")
    rows = [re.sub(r"\s+"," ", r).strip(" .") for r in t.splitlines()]
    rows = [r for r in rows if r and not r.lower().startswith(("instruksi","evaluasi"))]
    rep = {r"\bopg\b":"OPG X-ray", r"\bperiapikal\b":"Periapikal X-ray", r"\bkonsul\b":"Konsul interna", r"\bkonsultasi\b":"Konsultasi"}
    out, seen = [], set()
    for r in rows:
        x = r
        for k,v in rep.items(): x = re.sub(k, v, x, flags=re.I)
        kx = x.lower()
        if kx not in seen:
            out.append(x); seen.add(kx)
    return out

# ====== DPJP mapper ======
def map_dpjp(doctor: str) -> str:
    key = doctor.lower()
    if re.search(r"yossy|yoanita|ariestiana", key): return "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K)."
    if "ruslin" in key:   return "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)"
    if "gazali" in key:   return "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)"
    if "carolina" in key or "stevanie" in key: return "drg. Carolina Stevanie, Sp.B.M.M."
    return ""

# ====== parser HTML (fix 7 kolom CPPT) ======
def parse_html_record(html_text: str):
    soup = BeautifulSoup(html_text, "html.parser")

    # header biodata
    nama = rm = tgl = tel = ""
    header = soup.select_one("table.tbl_form")
    if header:
        for tr in header.select("tr.isi"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                label = re.sub(r"\s+"," ", tds[0].get_text(strip=True))
                val   = tds[2].get_text(" ", strip=True)
                if re.search(r"No\.?\s*RM", label, re.I): rm = val
                elif re.search(r"Nama\s*Pasien", label, re.I): nama = val.title()
                elif re.search(r"Tempat.*Tanggal\s*Lahir", label, re.I):
                    m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})", val)
                    if m: tgl = m.group(1)
                elif re.search(r"Nomor\s*Telepon", label, re.I):
                    mt = re.search(r"(08\d{8,13})", val)
                    tel = mt.group(1) if mt else val

    # inner CPPT table (7 kolom)
    inner = None
    for t in soup.select("table.tbl_form table"):
        if "Tanggal" in t.text and "Plan/Monitoring" in t.text:
            inner = t; break

    latest = None
    if inner:
        rows = inner.find_all("tr", class_="isi")
        if len(rows) >= 2:
            data = rows[1].find_all("td")
            # mapping 7 kolom
            if len(data) >= 6:
                dt   = data[0].get_text(" ", strip=True)
                doc  = data[1].get_text(" ", strip=True)
                ai   = data[4].get_text(" ", strip=True)
                plan = data[5].get_text(" ", strip=True)
                instr= data[6].get_text(" ", strip=True) if len(data)>=7 else ""
                latest = {"dt": dt, "doctor": doc, "ai": ai, "plan": plan, "instr": instr}

    return {"nama": nama, "rm": rm, "tgl": tgl, "tel": tel, "cppt": latest}

# ====== derive & build one review (EXACT spacing) ======
def build_review(rec, operator: str, index_no: int):
    nama = rec.get("nama","")
    rm   = format_rm(rec.get("rm",""))
    tgl  = format_date_ddmmyyyy(rec.get("tgl",""))
    tel  = rec.get("tel","")

    cppt = rec.get("cppt") or {}
    dpjp = map_dpjp(cppt.get("doctor",""))
    diag_items = split_diag(cppt.get("ai",""))
    plan_items = split_plan(cppt.get("plan",""), cppt.get("instr",""))

    tindakan = [x for x in plan_items if not re.match(r"(?i)pro\b", x)]
    kontrols = []
    for it in plan_items:
        if re.match(r"(?i)pro\b", it):
            m = re.search(r"(?i)pro\s+odontektomi(?:\s+gigi)?\s*(\d{2})", it)
            if m:
                kontrols.append(f"Pro Odontektomi gigi {m.group(1)} dalam lokal anestesi")
            else:
                kontrols.append(it)

    # tambah Konsultasi bila ada X-ray di tindakan
    if any(re.search(r"(?i)x[- ]?ray|opg|periapikal", x) for x in tindakan):
        if all("konsultasi" not in x.lower() for x in tindakan):
            tindakan.insert(0, "Konsultasi")

    ctrl = next((k for k in kontrols if "odontektomi" in k.lower()), kontrols[0] if kontrols else "")

    lines = []
    lines.append(f"{index_no}. {fmt_main('Nama', nama)}")
    lines.append(fmt_bullet("Tanggal Lahir", tgl))
    lines.append(fmt_bullet("RM", rm))
    lines.append(fmt_head("Diagnosa"))
    for d in diag_items:
        lines.append(f"    * {d}")
    if len(tindakan) <= 1:
        lines.append(fmt_bullet("Tindakan", tindakan[0] if tindakan else ""))
    else:
        lines.append(fmt_head("Tindakan"))
        for t in tindakan:
            lines.append(f"    * {t}")
    lines.append(fmt_bullet("Kontrol", ctrl))
    lines.append(fmt_bullet("DPJP", dpjp))
    lines.append(fmt_bullet("No. Telp.", tel))
    lines.append(fmt_bullet("Operator", operator or ""))
    return "\n".join(lines)
