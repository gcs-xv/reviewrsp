import re
from io import BytesIO
from typing import List, Dict, Any

import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

# =========================
# Formatting helpers (PERSIS)
# =========================
LABEL_COL = 15  # "Nama            :"
def fmt_main(label: str, value: str) -> str:
    return f"{label:<{LABEL_COL}} : {value}".rstrip()

def fmt_bullet(label: str, value: str) -> str:
    # "• Tanggal Lahir  : 13/04/2004"
    return f"• {label:<{LABEL_COL}} : {value}".rstrip()

def fmt_bullet_head(label: str) -> str:
    # line head for multi-line sections: "• Tindakan        :"
    return f"• {label:<{LABEL_COL}} :"

# =========================
# Canon data
# =========================
DPJP_CANON = [
    "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)",
    "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K).",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)",
    "drg. Carolina Stevanie, Sp.B.M.M.",
]
def map_dpjp(raw: str) -> str:
    key = re.sub(r"[^a-z]", "", (raw or "").lower())
    if not key: return raw or ""
    if "yossy" in key or "yoanita" in key or "ariestiana" in key:
        return DPJP_CANON[1]
    if "ruslin" in key:
        return DPJP_CANON[0]
    if "gazali" in key:
        return DPJP_CANON[2]
    if "carolina" in key or "stevanie" in key:
        return DPJP_CANON[3]
    # fallback if already canonical-ish
    for c in DPJP_CANON:
        if re.sub(r"[^a-z]","", c.lower()) in key or key in re.sub(r"[^a-z]","", c.lower()):
            return c
    return raw

# =========================
# Text utils
# =========================
def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def title_keep(s: str) -> str:
    return " ".join(w.capitalize() for w in norm(s).split())

def format_rm(rm: str) -> str:
    d = re.sub(r"\D", "", rm or "")
    if not d: return ""
    if len(d) == 6:
        parts = [d[0:2], d[2:4], d[4:6]]
    elif len(d) == 7:
        parts = [d[0:1], d[1:3], d[3:5], d[5:7]]
    else:
        parts = [d[i:i+2] for i in range(0, len(d), 2)]
    return ".".join([p for p in parts if p])

def format_date_ddmmyyyy(s: str) -> str:
    s = (s or "").strip()
    if not s: return ""
    # accept 2004-09-04 or 04-09-2004, etc.
    try:
        dt = dtparser.parse(s, dayfirst=False, fuzzy=True)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        m = re.search(r"(\d{2})[-/.](\d{2})[-/.](\d{4})", s)
        if m: return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
        m = re.search(r"(\d{4})[-/.](\d{2})[-/.](\d{2})", s)
        if m: return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
        return s

# =========================
# Parser HTML SIMRS
# =========================
def parse_html_patient(html_text: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_text, "html.parser")

    # HEADER biodata: table.tbl_form (label di kolom 1, value di kolom 3)
    header = soup.select_one("table.tbl_form")
    nama = rm = tgl = tel = ""
    if header:
        for tr in header.select("tr.isi"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                label = norm(tds[0].get_text())
                val = tds[2].get_text(" ", strip=True)
                if re.search(r"No\.?\s*RM", label, re.I):
                    rm = val
                elif re.search(r"Nama\s*Pasien", label, re.I):
                    nama = val
                elif re.search(r"Tempat.*Tanggal\s*Lahir", label, re.I):
                    m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})", val)
                    if m: tgl = m.group(1)
                elif re.search(r"Nomor\s*Telepon", label, re.I):
                    mt = re.search(r"(08\d{8,13})", val)
                    tel = mt.group(1) if mt else val

    # CPPT rows: cari rows dengan 8 kolom (Tanggal, Dokter, Subjek, Objek/Diagnosis, Asesmen/Intervensi, Plan, Instruksi, Evaluasi)
    cppt_rows = []
    for big in soup.select("table.tbl_form"):
        for t in big.select("table"):
            for tr in t.select("tr.isi"):
                tds = tr.find_all("td")
                if len(tds) == 8:
                    tanggal_html = tds[0].decode_contents()
                    ds = re.findall(r"(\d{4}-\d{2}-\d{2})", tanggal_html)
                    hs = re.findall(r"(\d{2}:\d{2}:\d{2})", tanggal_html)
                    if not ds: continue
                    dt_str = ds[-1] + (" " + hs[-1] if hs else " 00:00:00")
                    try:
                        dt = dtparser.parse(dt_str)
                    except Exception:
                        continue
                    cppt_rows.append({
                        "dt": dt,
                        "dokter": norm(tds[1].get_text(" ", strip=True)),
                        "subjek": norm(tds[2].get_text(" ", strip=True)),
                        "obj_diag": norm(tds[3].get_text(" ", strip=True)),
                        "ai": norm(tds[4].get_text(" ", strip=True)),
                        "plan": norm(tds[5].get_text(" ", strip=True)),
                        "instruksi": norm(tds[6].get_text(" ", strip=True)),
                        "eval": norm(tds[7].get_text(" ", strip=True)),
                    })

    latest = max(cppt_rows, key=lambda r: r["dt"]) if cppt_rows else None

    return {
        "nama": title_keep(nama),
        "rm": rm,
        "tgl": tgl,
        "tel": tel,
        "cppt": latest
    }

# =========================
# Business rules (Diagnosa/Tindakan/Kontrol)
# =========================
def split_diag(ai_text: str) -> List[str]:
    """
    Pecah diagnosa di A/I menjadi bullet yang rapi:
    - pisah berdasarkan koma atau ' ; '
    - normalisasi 'impaksi' -> 'Impaksi gigi ...', 'perikoronitis' -> 'Perikoronitis gigi ...' jika ada nomor gigi
    """
    if not ai_text: return []
    raw = re.split(r"[;,]\s*", ai_text)
    items = []
    for r in raw:
        s = norm(r)
        if not s: continue
        # normalisasi kapital
        s = s[0].upper() + s[1:] if len(s) > 1 else s.upper()
        # jika ada nomor gigi, tambahkan kata 'gigi' jika belum ada
        mg = re.findall(r"\b(\d{2})\b", s)
        if mg and "gigi" not in s.lower():
            # contoh: "Impaksi 18,28,38,48" -> "Impaksi gigi 18,28,38,48"
            s = re.sub(r"(\d{2}(?:\s*,\s*\d{2})+|\d{2})", r"gigi \1", s, count=1)
        items.append(s)
    # gabung item yang terlalu pendek / duplikat
    out, seen = [], set()
    for x in items:
        k = x.lower()
        if k not in seen:
            out.append(x)
            seen.add(k)
    return out

def split_plan(plan_text: str, instruksi_text: str) -> List[str]:
    if not plan_text and not instruksi_text: return []
    t = " ; ".join([plan_text or "", instruksi_text or ""])
    t = t.replace("•", "\n").replace("·", "\n")
    t = re.sub(r"\s*[-–]\s*", "\n", t)
    t = t.replace(",", "\n")
    rows = [re.sub(r"\s+", " ", r).strip(" .") for r in t.splitlines()]
    rows = [r for r in rows if r and not r.lower().startswith(("instruksi", "evaluasi"))]
    # normalisasi istilah
    rep = {
        r"\bopg\b": "OPG X-ray",
        r"\bperiapikal\b": "Periapikal X-ray",
        r"\bkonsul\b": "Konsul interna",
        r"\bkonsultasi\b": "Konsultasi",
    }
    normed, seen = [], set()
    for r in rows:
        x = r
        for k, v in rep.items():
            x = re.sub(k, v, x, flags=re.I)
        kx = x.lower()
        if kx not in seen:
            normed.append(x)
            seen.add(kx)
    return normed

def derive_sections(ai_text: str, plan_text: str, instruksi_text: str):
    # Diagnosa
    diag_items = split_diag(ai_text)

    # Plan → pisah tindakan & kontrol
    plan_items = split_plan(plan_text, instruksi_text)

    tindakan = []
    kontrol_items = []
    for it in plan_items:
        if re.match(r"(?i)pro\b", it):
            # khusus odontektomi -> pastikan "gigi NN dalam lokal anestesi"
            m = re.search(r"(?i)pro\s+odontektomi(?:\s+gigi)?\s*(\d{2})", it)
            if m:
                gnum = m.group(1)
                it_fmt = f"Pro Odontektomi gigi {gnum} dalam lokal anestesi"
                kontrol_items.append(it_fmt)
            else:
                kontrol_items.append(it)
        else:
            tindakan.append(it)

    # Heuristik konsultasi: jika ada X-ray dalam tindakan hari itu, tambahkan "Konsultasi" (kalau belum ada)
    if any(re.search(r"(?i)x[- ]?ray|opg|periapikal", x) for x in tindakan):
        if all("konsultasi" not in x.lower() for x in tindakan):
            tindakan.insert(0, "Konsultasi")

    # Kontrol: jika kosong tetapi ada Pro di plan awal (kadang semua Pro), tetap list semua Pro
    if not kontrol_items and any(re.match(r"(?i)pro\b", it) for it in plan_items):
        kontrol_items = [it for it in plan_items if re.match(r"(?i)pro\b", it)]

    # Tindakan one-line vs bullet
    tindakan_is_single = len(tindakan) <= 1

    return diag_items, tindakan, tindakan_is_single, kontrol_items

# =========================
# Build review text (PERSIS)
# =========================
def build_review(record: Dict[str, Any], dpjp_override: str, operator: str, index_no: int) -> str:
    nama = record.get("nama","")
    rm = format_rm(record.get("rm",""))
    tgl = format_date_ddmmyyyy(record.get("tgl",""))
    tel = record.get("tel","")

    cppt = record.get("cppt")
    if cppt:
        dpjp = map_dpjp(cppt.get("dokter",""))
        ai = cppt.get("ai","")
        plan = cppt.get("plan","")
        instruksi = cppt.get("instruksi","")
    else:
        dpjp = ""
        ai = plan = instruksi = ""

    if dpjp_override:
        dpjp = dpjp_override

    diag_items, tindakan, tindakan_is_single, kontrol_items = derive_sections(ai, plan, instruksi)

    lines = []
    lines.append(f"{index_no}. {fmt_main('Nama', nama)}")
    lines.append(fmt_bullet("Tanggal Lahir", tgl))
    lines.append(fmt_bullet("RM", rm))
    if len(diag_items) <= 1:
        # kalau cuma satu diagnosa, tetap tampil multi-baris sesuai permintaan kamu: header + bullet
        lines.append(fmt_bullet_head("Diagnosa"))
        if diag_items:
            lines.append(f"    * {diag_items[0]}")
    else:
        lines.append(fmt_bullet_head("Diagnosa"))
        for d in diag_items:
            lines.append(f"    * {d}")

    if tindakan_is_single:
        val = tindakan[0] if tindakan else ""
        lines.append(fmt_bullet("Tindakan", val))
    else:
        lines.append(fmt_bullet_head("Tindakan"))
        for t in tindakan:
            lines.append(f"    * {t}")

    # Kontrol: jika banyak, tetap **satu baris** (sesuai contohmu? -> kamu minta satu item utama.
    # Di kasus kamu, kontrol fokus pada tindakan "Pro ..." utama; kita ambil yang paling “odontektomi” dulu, jika ada.
    ctrl_val = ""
    if kontrol_items:
        # Prioritaskan odontektomi
        odo = [k for k in kontrol_items if "odontektomi" in k.lower()]
        ctrl_val = odo[0] if odo else kontrol_items[0]
    lines.append(fmt_bullet("Kontrol", ctrl_val))

    lines.append(fmt_bullet("DPJP", dpjp))
    lines.append(fmt_bullet("No. Telp.", tel))
    lines.append(fmt_bullet("Operator", operator or ""))

    return "\n".join(lines)

# =========================
# STREAMLIT APP
# =========================
st.set_page_config(page_title="RSPTN Review (HTML)", page_icon="🩺", layout="centered")
st.title("🩺 RSPTN Review Generator — HTML (NO OCR)")

uploaded_files = st.file_uploader("Upload 1 atau lebih file HTML dari SIMRS", type=["html","htm"], accept_multiple_files=True)
col1, col2 = st.columns(2)
with col1:
    dpjp_override = st.selectbox("DPJP (opsional override untuk SEMUA)", ["(auto)"] + DPJP_CANON)
    if dpjp_override == "(auto)":
        dpjp_override = ""
with col2:
    operator_all = st.text_input("Operator (berlaku ke semua)", "")

if uploaded_files:
    # parse semua, urutkan berdasarkan dt CPPT terbaru di tiap file
    records: List[Dict[str,Any]] = []
    for f in uploaded_files:
        html_text = f.read().decode("utf-8", errors="ignore")
        rec = parse_html_patient(html_text)
        if rec.get("cppt"):
            records.append(rec)
        else:
            # tetap masuk, tapi dt None → ditaruh di belakang
            records.append(rec)

    # sort by dt desc (terbaru dulu) atau asc? Kamu minta 1..N untuk tanggal itu — kita urutkan ASCENDING jam
    records.sort(key=lambda r: r["cppt"]["dt"] if r.get("cppt") else dtparser.parse("1900-01-01"))

    # build reviews bernomor
    outputs = []
    for i, rec in enumerate(records, start=1):
        out = build_review(rec, dpjp_override, operator_all, i)
        outputs.append(out)

    final_text = "\n\n".join(outputs)

    st.success("✅ Review selesai (format persis).")
    st.code(final_text, language="markdown")
    st.download_button("⬇️ Download review.txt", final_text.encode("utf-8"), "review.txt", "text/plain")
else:
    st.info("Upload HTML SIMRS untuk mulai.")
