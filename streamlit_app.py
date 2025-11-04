import re
from typing import List, Dict, Any
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

# =========================
# Formatting (PERSIS sama)
# =========================
LABEL_COL = 15  # menghasilkan "Nama            :"
def fmt_main(label, val):   return f"{label:<{LABEL_COL}} : {val}".rstrip()
def fmt_bullet(label, val): return f"• {label:<{LABEL_COL}} : {val}".rstrip()
def fmt_head(label):        return f"• {label:<{LABEL_COL}} :"

def format_rm(rm: str) -> str:
    d = re.sub(r"\D", "", rm or "")
    if not d: return ""
    if len(d) == 6:
        parts = [d[:2], d[2:4], d[4:6]]
    elif len(d) == 7:
        parts = [d[:1], d[1:3], d[3:5], d[5:7]]
    else:
        parts = [d[i:i+2] for i in range(0, len(d), 2)]
    return ".".join([p for p in parts if p])

def format_date_ddmmyyyy(s: str) -> str:
    s = (s or "").strip()
    if not s: return ""
    try:
        dt = dtparser.parse(s, fuzzy=True, dayfirst=False)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        return s

# =========================
# Normalisasi & aturan
# =========================
def map_dpjp(doctor: str) -> str:
    key = (doctor or "").lower()
    if re.search(r"yossy|yoanita|ariestiana", key):
        return "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K)."
    if "ruslin" in key:
        return "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)"
    if "gazali" in key:
        return "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)"
    if "carolina" in key or "stevanie" in key:
        return "drg. Carolina Stevanie, Sp.B.M.M."
    return ""

def split_diag(ai_text: str) -> List[str]:
    s = " ".join((ai_text or "").split())
    out = []
    m = re.search(r'(?i)\bimpaksi\b\s*([0-9]{2}(?:\s*,\s*[0-9]{2})+|[0-9]{2})', s)
    if m:
        out.append(f"Impaksi gigi {m.group(1).replace(' ', '')}")
    m = re.search(r'(?i)\bperikoronitis\b\s*([0-9]{2}(?:\s*,\s*[0-9]{2})+|[0-9]{2})', s)
    if m:
        out.append(f"Perikoronitis gigi {m.group(1).replace(' ', '')}")
    if out:
        return out
    # fallback: pisah koma/semicolon
    parts = [p.strip() for p in re.split(r"[;,]\s*", s) if p.strip()]
    return [p[0].upper()+p[1:] if len(p)>1 else p.upper() for p in parts]

def split_plan(plan_text: str, instr_text: str = "") -> List[str]:
    t = " ; ".join([plan_text or "", instr_text or ""])
    # sisip newline sebelum kata "Pro ..." yang nempel
    t = re.sub(r"\s+(?=Pro\s)", "\n", t, flags=re.I)
    t = t.replace("•", "\n").replace("·", "\n")
    t = re.sub(r"\s*[-–]\s*", "\n", t)
    t = t.replace(",", "\n")
    rows = [re.sub(r"\s+", " ", r).strip(" .") for r in t.splitlines()]
    rows = [r for r in rows if r and not r.lower().startswith(("instruksi", "evaluasi"))]
    rep = {
        r"\bopg\b": "OPG X-ray",
        r"\bperiapikal\b": "Periapikal X-ray",
        r"\bkonsul\b": "Konsul interna",
        r"\bkonsultasi\b": "Konsultasi",
    }
    out, seen = [], set()
    for r in rows:
        x = r
        for k, v in rep.items():
            x = re.sub(k, v, x, flags=re.I)
        kx = x.lower()
        if kx not in seen:
            out.append(x); seen.add(kx)
    return out

def derive_sections(ai_text: str, plan_text: str, instr_text: str):
    diag_items = split_diag(ai_text)
    plan_items = split_plan(plan_text, instr_text)

    tindakan = [x for x in plan_items if not re.match(r"(?i)pro\b", x)]
    kontrol_items = []
    for it in plan_items:
        if re.match(r"(?i)pro\b", it):
            m = re.search(r"(?i)pro\s+odontektomi(?:\s+gigi)?\s*(\d{2})", it)
            if m:
                kontrol_items.append(f"Pro Odontektomi gigi {m.group(1)} dalam lokal anestesi")
            else:
                kontrol_items.append(it)

    # tambahkan "Konsultasi" jika ada X-ray/OPG/periapikal di tindakan
    if any(re.search(r"(?i)x[- ]?ray|opg|periapikal", x) for x in tindakan):
        if all("konsultasi" not in x.lower() for x in tindakan):
            tindakan.insert(0, "Konsultasi")

    tindakan_is_single = len(tindakan) <= 1
    # pilih kontrol utama (prioritaskan odontektomi)
    ctrl_val = ""
    if kontrol_items:
        odo = [k for k in kontrol_items if "odontektomi" in k.lower()]
        ctrl_val = odo[0] if odo else kontrol_items[0]

    return diag_items, tindakan, tindakan_is_single, ctrl_val

# =========================
# Parser HTML (NO OCR)
# =========================
def parse_html_record(html_text: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_text, "lxml")  # gunakan lxml biar stabil

    # --- Header biodata (table.tbl_form pertama)
    nama = rm = tgl = tel = ""
    header = soup.select_one("table.tbl_form")
    if header:
        for tr in header.select("tr.isi"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                label = re.sub(r"\s+", " ", tds[0].get_text(strip=True))
                val   = tds[2].get_text(" ", strip=True)
                if re.search(r"No\.?\s*RM", label, re.I):
                    rm = val
                elif re.search(r"Nama\s*Pasien", label, re.I):
                    nama = val.title()
                elif re.search(r"Tempat.*Tanggal\s*Lahir", label, re.I):
                    m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})", val)
                    if m: tgl = m.group(1)
                elif re.search(r"Nomor\s*Telepon", label, re.I):
                    mt = re.search(r"(08\d{8,13})", val)
                    tel = mt.group(1) if mt else val

    # --- Cari tabel CPPT yang kolomnya punya header Tanggal & Plan/Monitoring
    cppt_candidates = []
    for t in soup.select("table.tbl_form table"):
        txt = t.get_text(" ", strip=True)
        if "Tanggal" in txt and "Plan/Monitoring" in txt:
            cppt_candidates.append(t)
    inner = cppt_candidates[0] if cppt_candidates else None

    # --- Ambil SEMUA baris data (class=isi) → pilih yang tanggalnya paling akhir
    latest = None
    if inner:
        for tr in inner.find_all("tr", class_="isi"):
            tds = tr.find_all("td")
            # Beberapa export punya 7 kolom (0..6); jangan pakai ==7 rigid
            if len(tds) >= 6:
                tanggal_html = tds[0].get_text(" ", strip=True)
                # tanggal bisa dua baris, ambil pattern yyyy-mm-dd & hh:mm:ss
                d = re.search(r"(\d{4}-\d{2}-\d{2})", tanggal_html)
                h = re.search(r"(\d{2}:\d{2}:\d{2})", tanggal_html)
                if not d:  # jika kosong, skip
                    continue
                dt_str = d.group(1) + (" " + h.group(1) if h else " 00:00:00")
                try:
                    dt_obj = dtparser.parse(dt_str)
                except Exception:
                    continue
                row = {
                    "dt": dt_obj,
                    "doctor": tds[1].get_text(" ", strip=True) if len(tds) > 1 else "",
                    "subj":   tds[2].get_text(" ", strip=True) if len(tds) > 2 else "",
                    "obj":    tds[3].get_text(" ", strip=True) if len(tds) > 3 else "",
                    "ai":     tds[4].get_text(" ", strip=True) if len(tds) > 4 else "",
                    "plan":   tds[5].get_text(" ", strip=True) if len(tds) > 5 else "",
                    "instr":  tds[6].get_text(" ", strip=True) if len(tds) > 6 else "",
                }
                if (latest is None) or (row["dt"] > latest["dt"]):
                    latest = row

    return {
        "nama": nama, "rm": rm, "tgl": tgl, "tel": tel,
        "cppt": latest
    }

# =========================
# Build satu review (persis)
# =========================
def build_review(rec: Dict[str, Any], operator: str, index_no: int) -> str:
    nama = rec.get("nama", "")
    rm   = format_rm(rec.get("rm", ""))
    tgl  = format_date_ddmmyyyy(rec.get("tgl", ""))
    tel  = rec.get("tel", "")

    cppt = rec.get("cppt") or {}
    dpjp = map_dpjp(cppt.get("doctor", ""))
    diag_items, tindakan, tindakan_is_single, kontrol_val = derive_sections(
        cppt.get("ai", ""), cppt.get("plan", ""), cppt.get("instr", "")
    )

    lines = []
    lines.append(f"{index_no}. {fmt_main('Nama', nama)}")
    lines.append(fmt_bullet("Tanggal Lahir", tgl))
    lines.append(fmt_bullet("RM", rm))

    # Diagnosa (selalu header + bullets sesuai contohmu)
    lines.append(fmt_head("Diagnosa"))
    for d in diag_items:
        lines.append(f"    * {d}")

    # Tindakan
    if tindakan_is_single:
        lines.append(fmt_bullet("Tindakan", tindakan[0] if tindakan else ""))
    else:
        lines.append(fmt_head("Tindakan"))
        for t in tindakan:
            lines.append(f"    * {t}")

    lines.append(fmt_bullet("Kontrol", kontrol_val))
    lines.append(fmt_bullet("DPJP", dpjp))
    lines.append(fmt_bullet("No. Telp.", tel))
    lines.append(fmt_bullet("Operator", operator or ""))

    return "\n".join(lines)

# =========================
# STREAMLIT UI
# =========================
st.set_page_config(page_title="RSPTN Review (HTML only)", page_icon="🩺", layout="centered")
st.title("🩺 RSPTN Review Generator — HTML (tanpa OCR)")

uploaded_files = st.file_uploader("Upload 1 atau lebih file HTML (print from SIMRS)", type=["html", "htm"], accept_multiple_files=True)
operator_all = st.text_input("Operator (berlaku ke semua)", "")

if uploaded_files:
    # parse semua file
    records = []
    for f in uploaded_files:
        html = f.read().decode("utf-8", errors="ignore")
        rec = parse_html_record(html)
        records.append(rec)

    # urutkan ASC by dt cppt terbaru (yang lebih pagi muncul dulu → 1.,2.,3.,…)
    def _key_dt(r):
        cp = r.get("cppt")
        if not cp: return dtparser.parse("1900-01-01")
        return cp["dt"]
    records.sort(key=_key_dt)

    # build final
    outputs = []
    for i, rec in enumerate(records, start=1):
        outputs.append(build_review(rec, operator_all, i))
    final_text = "\n\n".join(outputs)

    st.success("✅ Review selesai.")
    st.code(final_text, language="markdown")
    st.download_button("⬇️ Download review.txt", final_text.encode("utf-8"), "review.txt", "text/plain")
else:
    st.info("Upload HTML dari SIMRS untuk memulai.")
