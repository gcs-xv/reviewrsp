import re
from typing import List, Dict, Any
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from datetime import date

# =============== FORMAT (persis contoh) ===============
LABEL_COL = 15
def fmt_main(label, val):   return f"{label:<{LABEL_COL}} : {val}".rstrip()
def fmt_bullet(label, val): return f"• {label:<{LABEL_COL}} : {val}".rstrip()
def fmt_head(label):        return f"• {label:<{LABEL_COL}} :"

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def format_rm(rm: str) -> str:
    d = re.sub(r"\D", "", rm or "")
    if not d: return ""
    if len(d)==6: parts=[d[:2], d[2:4], d[4:6]]
    elif len(d)==7: parts=[d[:1], d[1:3], d[3:5], d[5:7]]
    else: parts=[d[i:i+2] for i in range(0, len(d), 2)]
    return ".".join([p for p in parts if p])

def format_date_ddmmyyyy(s: str) -> str:
    s = (s or "").strip()
    if not s: return ""
    try:
        return dtparser.parse(s, fuzzy=True, dayfirst=False).strftime("%d/%m/%Y")
    except Exception:
        return s

# =============== DPJP mapping (4 nama) ===============
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

# =============== DIAGNOSA (gabung potongan) ===============
def _append_tooth_numbers(base: str, extra_nums: List[str]) -> str:
    base = base.rstrip(" ,;")
    return f"{base}, {', '.join(extra_nums)}"

def split_diag(ai_text: str) -> List[str]:
    """
    - Jangan pecah di 'ai'
    - Gabungkan angka gigi yang nyasar (mis. '27') ke item sebelumnya
    - 1 item total nanti ditampilkan inline
    """
    t = _clean(ai_text)
    raw = re.split(r"[;/]\s*", t)
    if len(raw) == 1:
        raw = re.split(r",\s*(?=[A-Z0-9])", t)

    items = []
    for ch in raw:
        ch = _clean(ch)
        if not ch: continue
        items.append(ch[0].upper()+ch[1:] if len(ch)>1 else ch.upper())
    if not items:
        return []

    merged, pending_nums = [], []
    for it in items:
        if re.fullmatch(r"\d{2}", it):  # baris cuma "17"/"27"
            pending_nums.append(it); continue
        if merged and pending_nums:
            merged[-1] = _append_tooth_numbers(merged[-1], pending_nums)
            pending_nums = []
        merged.append(_clean(it))
    if pending_nums and merged:
        merged[-1] = _append_tooth_numbers(merged[-1], pending_nums)

    return merged

# =============== PLAN → TINDAKAN/KONTROL ===============
EXCLUDE_NOT_ACTION = re.compile(
    r"(?i)\b(Resep|Jumlah|Aturan\s*Pakai|SPOIT|SYRINGE|TAB|CAPS|MG|AMPUL|ECOSORB|ECOSOL|PISAU|INF|IV|INFUS|OBAT|Jangan|Diet\b|Jaga\b)\b"
)

def split_plan(plan_text: str, instr_text: str = "") -> List[str]:
    """
    - Pisah 'OPG Pro ...' yang nempel
    - Buang resep/alat/edukasi
    - Normalisasi istilah
    - Tambah 'Cuci luka …' bila ada 'Aff hecting'
    """
    t = " ; ".join([plan_text or "", instr_text or ""])
    t = re.sub(r"\s+(?=Pro\s)", "\n", t, flags=re.I)
    t = t.replace("•", "\n").replace("·", "\n")
    t = re.sub(r"\s*[-–]\s*", "\n", t)
    t = t.replace(",", "\n")

    rows = [re.sub(r"\s+", " ", r).strip(" .;") for r in t.splitlines()]
    rows = [r for r in rows if r]

    normed: List[str] = []
    for r in rows:
        x = r
        x = re.sub(r"\bopg\b", "OPG X-ray", x, flags=re.I)
        x = re.sub(r"\bperiapikal\b", "Periapikal X-ray", x, flags=re.I)
        x = re.sub(r"\bkonsul\b", "Konsul interna", x, flags=re.I)
        x = re.sub(r"\bkonsultasi\b", "Konsultasi", x, flags=re.I)
        x = _clean(x)
        if not x or EXCLUDE_NOT_ACTION.search(x):  # buang non tindakan
            continue

        # Normalisasi tindakan utama → “... gigi NN dalam lokal anestesi”
        m = re.search(r"(?i)\bodontektomi\b(?:\s+gigi)?\s*(\d{2})", x)
        if m: x = f"Odontektomi gigi {m.group(1)} dalam lokal anestesi"
        m = re.search(r"(?i)\bekstrak[si]\w*\b(?:\s+gigi)?\s*(\d{2})", x)
        if m: x = f"Ekstraksi gigi {m.group(1)} dalam lokal anestesi"

        # hapus sisa "Resep: ..."
        x = re.sub(r"(?i)\bResep\b.*", "", x).strip(" ;")
        if x and x not in normed:
            normed.append(x)

    # Aff hecting → tambahkan "Cuci luka …" bila belum ada
    if any(re.search(r"(?i)\baff?\s*hecting\b|\bhecting\b", s) for s in normed):
        if not any(re.search(r"(?i)\bcuci luka\b", s) for s in normed):
            normed.insert(0, "Cuci luka intra oral dengan NaCL 0.9%")

    return normed

def derive_sections(ai_text: str, plan_text: str, instr_text: str):
    diag_items = split_diag(ai_text)
    plan_items = split_plan(plan_text, instr_text)

    tindakan = [x for x in plan_items if not re.match(r"(?i)pro\b", x)]
    pro_items = [x for x in plan_items if re.match(r"(?i)pro\b", x)]

    # default kontrol dari "Pro ..."
    kontrol_default = ""
    if pro_items:
        m = None
        for it in pro_items:
            m = re.search(r"(?i)pro\s+odontektomi(?:\s+gigi)?\s*(\d{2})", it)
            if m: 
                kontrol_default = f"Pro Odontektomi gigi {m.group(1)} dalam lokal anestesi"; break
        if not kontrol_default:
            kontrol_default = pro_items[0]

    # tambah Konsultasi kalau ada X-ray
    if any(re.search(r"(?i)x[- ]?ray|opg|periapikal", x) for x in tindakan):
        if all("konsultasi" not in x.lower() for x in tindakan):
            tindakan.insert(0, "Konsultasi")

    tindakan_is_single = len(tindakan) <= 1
    return diag_items, tindakan, tindakan_is_single, kontrol_default

# =============== PARSE HTML (pilih baris di TANGGAL TARGET) ===============
def parse_html_record_for_date(html_text: str, target: date) -> Dict[str, Any]:
    soup = BeautifulSoup(html_text, "lxml")

    # header biodata
    nama = rm = tgl = tel = ""
    header = soup.select_one("table.tbl_form")
    if header:
        for tr in header.select("tr.isi"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                label = _clean(tds[0].get_text(strip=True))
                val   = tds[2].get_text(" ", strip=True)
                if re.search(r"No\.?\s*RM", label, re.I): rm = val
                elif re.search(r"Nama\s*Pasien", label, re.I): nama = val.title()
                elif re.search(r"Tempat.*Tanggal\s*Lahir", label, re.I):
                    m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})", val)
                    if m: tgl = m.group(1)
                elif re.search(r"Nomor\s*Telepon", label, re.I):
                    mt = re.search(r"(08\d{8,13})", val)
                    tel = mt.group(1) if mt else val

    # cari tabel CPPT dan kumpulkan baris yang **tanggalnya = target**
    chosen = None
    for t in soup.select("table.tbl_form table"):
        txt = t.get_text(" ", strip=True)
        if "Tanggal" not in txt or "Plan/Monitoring" not in txt:
            continue
        for tr in t.find_all("tr", class_="isi"):
            tds = tr.find_all("td")
            if len(tds) < 6: 
                continue
            td0 = tds[0].get_text(" ", strip=True)
            d = re.search(r"(\d{4}-\d{2}-\d{2})", td0)
            h = re.search(r"(\d{2}:\d{2}:\d{2})", td0)
            if not d:
                continue
            dt_obj = dtparser.parse(d.group(1) + (" " + (h.group(1) if h else "00:00:00")))
            if dt_obj.date() != target:
                continue
            row = {
                "dt": dt_obj,
                "doctor": tds[1].get_text(" ", strip=True) if len(tds) > 1 else "",
                "ai":     tds[4].get_text(" ", strip=True) if len(tds) > 4 else "",
                "plan":   tds[5].get_text(" ", strip=True) if len(tds) > 5 else "",
                "instr":  tds[6].get_text(" ", strip=True) if len(tds) > 6 else "",
            }
            if (chosen is None) or (row["dt"] > chosen["dt"]):
                chosen = row

    return {"nama": nama, "rm": rm, "tgl": tgl, "tel": tel, "cppt": chosen}

# =============== BUILD REVIEW (termasuk RULE KONTROL BARU) ===============
def build_review(rec: Dict[str, Any], operator: str, index_no: int) -> str:
    nama = rec.get("nama", "")
    rm   = format_rm(rec.get("rm", ""))
    tgl  = format_date_ddmmyyyy(rec.get("tgl", ""))
    tel  = rec.get("tel", "")
    cppt = rec.get("cppt") or {}

    dpjp = map_dpjp(cppt.get("doctor", ""))

    diag_items, tindakan, tindakan_is_single, kontrol_default = derive_sections(
        cppt.get("ai", ""), cppt.get("plan", ""), cppt.get("instr", "")
    )

    # ---- RULE KONTROL BARU ----
    # 1) Jika tindakan mengandung Ekstraksi/Odontektomi hari itu → Kontrol = POD VII
    tindakan_main = next((t for t in tindakan if re.search(r"(?i)\b(Ekstraksi|Odontektomi)\b", t)), None)
    # 2) Jika diagnosa mengandung 'POD VII' → Kontrol = '-'
    is_pod7_case = any(re.search(r"(?i)\bPOD\s*VII\b", d) for d in diag_items)

    if tindakan_main:
        kontrol_val = "POD VII"
    elif is_pod7_case:
        kontrol_val = "-"
    else:
        kontrol_val = kontrol_default  # fallback dari "Pro ...", kalau ada

    # ---- CETAK ----
    lines = []
    lines.append(f"{index_no}. {fmt_main('Nama', nama)}")
    lines.append(fmt_bullet("Tanggal Lahir", tgl))
    lines.append(fmt_bullet("RM", rm))

    # Diagnosa: 1 item inline, >1 bullets
    if len(diag_items) <= 1:
        lines.append(fmt_bullet("Diagnosa", diag_items[0] if diag_items else ""))
    else:
        lines.append(fmt_head("Diagnosa"))
        for d in diag_items:
            lines.append(f"    * {d}")

    # Tindakan: 1 item inline, >1 bullets
    if tindakan_is_single:
        lines.append(fmt_bullet("Tindakan", tindakan[0] if tindakan else ""))
    else:
        lines.append(fmt_head("Tindakan"))
        for t in tindakan:
            lines.append(f"    * {t}")

    lines.append(fmt_bullet("Kontrol", kontrol_val or ""))
    lines.append(fmt_bullet("DPJP", dpjp))
    lines.append(fmt_bullet("No. Telp.", tel))
    lines.append(fmt_bullet("Operator", operator or ""))

    return "\n".join(lines)

# =============== STREAMLIT UI ===============
st.set_page_config(page_title="RSPTN Review (HTML + Tanggal)", page_icon="🩺", layout="centered")
st.title("🩺 RSPTN Review Generator — HTML (filter per tanggal)")

colA, colB = st.columns([1,1])
with colA:
    target_date = st.date_input("Tanggal yang dilihat", value=date.today())
with colB:
    operator_all = st.text_input("Operator (berlaku ke semua)", "")

uploaded_files = st.file_uploader(
    "Upload 1 atau lebih file HTML (Print → Save as HTML dari SIMRS)",
    type=["html", "htm"], accept_multiple_files=True
)

if uploaded_files:
    records = []
    for f in uploaded_files:
        html = f.read().decode("utf-8", errors="ignore")
        rec = parse_html_record_for_date(html, target=target_date)
        if rec.get("cppt"):  # hanya yang punya baris pada tanggal target
            records.append(rec)

    if not records:
        st.warning("Tidak ada CPPT pada tanggal yang dipilih di file-file yang diupload.")
    else:
        # urutkan ASC by jam pada tanggal target
        records.sort(key=lambda r: r["cppt"]["dt"])
        outputs = [build_review(r, operator_all, i) for i, r in enumerate(records, start=1)]
        final_text = "\n\n".join(outputs)

        st.success("✅ Review selesai.")
        st.code(final_text, language="markdown")
        st.download_button("⬇️ Download review.txt", final_text.encode("utf-8"),
                           file_name="review.txt", mime="text/plain")
else:
    st.info("Pilih tanggal lalu upload HTML dari SIMRS.")
