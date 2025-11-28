import re
from typing import List, Dict, Any
from datetime import date, timedelta
import streamlit as st
from bs4 import BeautifulSoup
from dateutil import parser as dtparser

# ============== FORMAT (kolon & spasi rata, cocok untuk copas ke WA) ==============
# Lebar kolom label; kalau mau colonnya lebih ke kanan, boleh ganti mis. 20 atau 22.
LABEL_COL = 20

def fmt_main(label, val):
    # Pad label dengan spasi biasa supaya kira-kira sejajar di kebanyakan aplikasi (WA, Notes, dll).
    return f"{label:<{LABEL_COL}} : {val}".rstrip()

def fmt_bullet(label, val):
    # Versi bullet dengan padding label yang sama.
    return f"• {label:<{LABEL_COL}} : {val}".rstrip()

def fmt_head(label):
    # Header untuk bagian multi-item (Diagnosa:, Tindakan:)
    return f"• {label:<{LABEL_COL}} :"

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

# ============== DPJP mapping (4 nama) ==============
def map_dpjp(doctor: str) -> str:
    key = (doctor or "").lower()
    if re.search(r"yossy|yoanita|ariestiana", key):
        return "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K)"
    if "ruslin" in key:
        return "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)"
    if "gazali" in key:
        return "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)"
    if "carolina" in key or "stevanie" in key:
        return "drg. Carolina Stevanie, Sp.B.M.M"
    return ""

# ============== DIAGNOSA (gabung potongan, 1 item = inline) ==============
def _append_tooth_numbers(base: str, extras: List[str]) -> str:
    base = base.rstrip(" ,;")
    return f"{base}, {', '.join(extras)}"

def _merge_impaksi_perikoronitis(items: List[str]) -> List[str]:
    if not items: return items
    out = []
    i = 0
    while i < len(items):
        cur = items[i]
        nxt = items[i+1] if i+1 < len(items) else ""
        if nxt and re.match(r"^\d{2}", nxt) and re.search(r"(?i)\bperikoronitis\b", nxt):
            if re.search(r"(?i)\bimpaksi\b", cur):
                lead_nums = re.findall(r"^\d{2}", nxt)
                if lead_nums:
                    if re.search(r",\s*\d{2}\s*$", cur):
                        cur = cur + ", " + lead_nums[0]
                    else:
                        m = re.search(r"(Impaksi(?:\s*gigi)?\s*)(.*)", cur, flags=re.I)
                        if m:
                            cur = m.group(1) + (m.group(2)+", " + lead_nums[0]).strip()
            nxt_fixed = re.sub(r"^\d{2}\s*,\s*", "", nxt).strip()
            out.append(cur)
            out.append(nxt_fixed[0].upper()+nxt_fixed[1:] if len(nxt_fixed)>1 else nxt_fixed.upper())
            i += 2
            continue
        out.append(cur)
        i += 1
    return out

def split_diag(ai_text: str) -> List[str]:
    """
    - Jangan pecah di 'ai'
    - Pisah di ';' atau '-' panjang; koma hanya memisah jika diikuti huruf besar/angka (kalimat baru)
    - Gabungkan angka gigi yang 'nyasar' (baris '27' dsb) ke item sebelumnya
    - Perbaiki pola impaksi/perikoronitis seperti contoh user
    - Tambahan aturan: hentikan di 'ai' (tidak perlu disertakan)
    """
    t = _clean(ai_text)
    # autocorrect common typo
    t = re.sub(r"(?i)impkasi", "impaksi", t)

    # ✅ Rule baru: stop di 'ai' dan buang sisanya
    if re.search(r"\bai\b", t, flags=re.I):
        t = re.split(r"\bai\b", t, flags=re.I)[0].strip()

    raw = re.split(r"[;/–—]\s*", t)
    if len(raw) == 1:
        raw = re.split(r",\s*(?=[A-Z0-9])", t)

    items = []
    for ch in raw:
        ch = _clean(ch)
        if not ch: continue
        items.append(ch[0].upper()+ch[1:] if len(ch)>1 else ch.upper())
    if not items:
        return []

    merged, pending = [], []
    for it in items:
        if re.fullmatch(r"\d{2}", it):
            pending.append(it); continue
        if merged and pending:
            merged[-1] = _append_tooth_numbers(merged[-1], pending); pending=[]
        merged.append(_clean(it))
    if pending and merged:
        merged[-1] = _append_tooth_numbers(merged[-1], pending)

    merged = _merge_impaksi_perikoronitis(merged)
    return merged

# ============== PLAN → TINDAKAN/KONTROL (Plan only!) ==============
EXCLUDE_NOT_ACTION = re.compile(
    r"(?i)\b(Resep|Jumlah|Aturan\s*Pakai|SPOIT|SYRINGE|TAB|CAPS|MG|AMPUL|ECOSORB|ECOSOL|PISAU|INF|IV|INFUS|OBAT|Jangan|Diet\b|Jaga\b|post operasi)\b"
)

def split_plan_only(plan_text: str) -> List[str]:
    t = _clean(plan_text)
    # pisah sebelum "Pro ..." jika nempel di belakang tindakan lain
    t = re.sub(r"\s+(?=Pro\s)", "\n", t, flags=re.I)
    # ganti bullet jadi newline
    t = t.replace("•", "\n").replace("·", "\n")
    # pisah di dash
    t = re.sub(r"\s*[-–—]\s*", "\n", t)
    # koma yang bukan pemisah angka gigi → newline
    t = re.sub(r",(?!\s?\d{2}\b)", "\n", t)

    rows = [re.sub(r"\s+", " ", r).strip(" .;") for r in t.splitlines()]

    # normalisasi tulisan Thorax xray
    rows = [re.sub(r"(?i)Thorax\s*xray", "Thorax X-ray", r) for r in rows]

    # pisahkan "Thorax X-ray Konsul Cardio (EKG)" → ["Thorax X-ray", "Konsul Cardio (EKG)"]
    new_rows: List[str] = []
    for r in rows:
        m = re.search(r"(?i)Konsul\s*Cardio", r)
        if m:
            before = r[:m.start()].strip()
            after  = r[m.start():].strip()
            if before:
                new_rows.append(before)
            if after:
                new_rows.append(after)
        else:
            new_rows.append(r)
    rows = [r for r in new_rows if r]

    normed: List[str] = []
    for r in rows:
        x = r
        # normalisasi istilah imaging
        x = re.sub(r"\bopg\b", "OPG X-ray", x, flags=re.I)
        x = re.sub(r"\bperiapikal\b", "Periapikal X-ray", x, flags=re.I)
        # hanya benahi kapitalisasi "konsul interna"; jangan ubah semua "konsul" jadi interna
        x = re.sub(r"(?i)konsul\s+interna", "Konsul interna", x)
        # benahi kapitalisasi konsultasi
        x = re.sub(r"(?i)konsultasi", "Konsultasi", x)
        # buang bagian setelah kata "Resep" supaya tindakan tidak hilang oleh teks resep
        x = re.sub(r"(?i)\bResep\b.*", "", x)
        x = _clean(x)

        # perbaiki pola OPG X / X ray yang kepotong → jadi satu "OPG X-ray"
        if re.search(r"OPG\s*X", x, flags=re.I) or re.search(r"X\s*ray", x, flags=re.I):
            if re.search(r"(?i)\bopg\b", x):
                x = "OPG X-ray"
        # buang baris "ray" sendirian
        if x.lower() == "ray":
            continue

        # filter edukasi, diet, obat, alat, dll (bukan tindakan)
        if not x or EXCLUDE_NOT_ACTION.search(x):
            continue

        # Normalisasi teks tindakan utama menjadi pola baku
        m = re.search(r"(?i)\bodontektomi\b(?:\s+gigi)?\s*(\d{2})", x)
        if m:
            x = f"Odontektomi gigi {m.group(1)} dalam lokal anestesi"
        m = re.search(r"(?i)\bekstrak[si]\w*\b(?:\s+gigi)?\s*(\d{2})", x)
        if m:
            x = f"Ekstraksi gigi {m.group(1)} dalam lokal anestesi"

        x = x.strip(" ;")
        if x and x not in normed:
            normed.append(x)

    # kalau ada aff hecting → pastikan cuci luka ikut
    if any(re.search(r"(?i)\baff?\s*hecting\b|\bhecting\b", s) for s in normed):
        if not any(re.search(r"(?i)\bcuci luka\b", s) for s in normed):
            normed.insert(0, "Cuci luka intra oral dengan NaCL 0.9%")

    return normed

def derive_sections(ai_text: str, plan_text: str):
    diag_items = split_diag(ai_text)
    plan_items = split_plan_only(plan_text)

    tindakan = [x for x in plan_items if not re.match(r"(?i)pro\b", x)]
    pro_items = [x for x in plan_items if re.match(r"(?i)pro\b", x)]

    kontrol_default = ""
    if pro_items:
        got = None
        for it in pro_items:
            m = re.search(r"(?i)pro\s+odontektomi(?:\s+gigi)?\s*(\d{2})", it)
            if m:
                got = f"Pro Odontektomi gigi {m.group(1)} dalam lokal anestesi"; break
        kontrol_default = got or pro_items[0]

    if any(re.search(r"(?i)x[- ]?ray|opg|periapikal", x) for x in tindakan):
        if all("konsultasi" not in x.lower() for x in tindakan):
            tindakan.insert(0, "Konsultasi")

    # Add rule: for diag items containing "POD VII" with "Odontektomi" or "Ekstraksi", append "dalam lokal anestesi" if missing.
    for i, d in enumerate(diag_items):
        if "POD VII" in d:
            if re.search(r"(?i)(Odontektomi|Ekstraksi)", d) and "dalam lokal anestesi" not in d.lower():
                diag_items[i] = d.strip() + " dalam lokal anestesi"

    single_tindakan = (len(tindakan) <= 1)
    return diag_items, tindakan, single_tindakan, kontrol_default

# ============== PARSE HTML (ambil hanya baris di TANGGAL TARGET) ==============
def parse_html_record_for_date(html_text: str, target: date) -> Dict[str, Any]:
    soup = BeautifulSoup(html_text, "lxml")

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

    chosen = None
    rows = []
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
            }
            rows.append(row)

    # Filter rows by doctor names (case-insensitive)
    valid_doctors = ["ruslin","yossy","gazali","carolina","stevanie"]
    filtered_rows = [r for r in rows if any(name in r["doctor"].lower() for name in valid_doctors)]

    if filtered_rows:
        chosen_rows = filtered_rows
    else:
        chosen_rows = rows

    for row in chosen_rows:
        if (chosen is None) or (row["dt"] > chosen["dt"]):
            chosen = row

    return {"nama": nama, "rm": rm, "tgl": tgl, "tel": tel, "cppt": chosen}

# ============== KONTROL (aturan barumu) ==============
def compute_kontrol(diag_items: List[str], tindakan: List[str], default_kontrol: str, when: date) -> str:
    # New rule:
    # If diagnosis contains "Impaksi gigi XX" and tindakan list contains "Konsultasi" or "OPG X-ray",
    # return Pro Odontektomi gigi XX dalam lokal anestesi.
    for d in diag_items:
        m_impaksi = re.search(r"(?i)impaksi gigi (\d{2})", d)
        if m_impaksi and any(t.lower() in ["konsultasi", "opg x-ray"] for t in tindakan):
            return f"Pro Odontektomi gigi {m_impaksi.group(1)} dalam lokal anestesi"
        m_gangren = re.search(r"(?i)gangren (pulpa|radiks) gigi (\d{2})", d)
        if m_gangren and any(t.lower() in ["konsultasi", "opg x-ray"] for t in tindakan):
            return f"Pro Ekstraksi gigi {m_gangren.group(2)} dalam lokal anestesi"
    if any(re.search(r"(?i)\b(Ekstraksi|Odontektomi)\b", t) for t in tindakan):
        return "POD VII"
    if any(re.search(r"(?i)\bPOD\s*VII\b", d) for d in diag_items):
        if any(re.search(r"(?i)(hemimandibulektomi|rekonstruksi)", d) for d in diag_items):
            dtx = when + timedelta(days=3)
            hari = ["senin","selasa","rabu","kamis","jumat","sabtu","minggu"][dtx.weekday()]
            return f"POD X ({hari},{dtx.strftime('%d/%m/%Y')})"
        return "-"
    return default_kontrol or "-"

# ============== BUILD REVIEW (format persis) ==============
def build_review(rec: Dict[str, Any], operator: str, index_no: int, target_day: date) -> str:
    nama = rec.get("nama", "")
    rm   = format_rm(rec.get("rm", ""))
    tgl  = format_date_ddmmyyyy(rec.get("tgl", ""))
    tel  = rec.get("tel", "")
    cppt = rec.get("cppt") or {}

    dpjp = map_dpjp(cppt.get("doctor", ""))
    diag_items, tindakan, single_tindakan, kontrol_default = derive_sections(
        cppt.get("ai", ""), cppt.get("plan", "")
    )
    kontrol_val = compute_kontrol(diag_items, tindakan, kontrol_default, target_day)

    lines = []
    lines.append(f"{index_no}. {fmt_main('Nama', nama)}")
    lines.append(fmt_bullet("Tanggal lahir", tgl))
    lines.append(fmt_bullet("RM", rm))

    if len(diag_items) <= 1:
        lines.append(fmt_bullet("Diagnosa", diag_items[0] if diag_items else ""))
    else:
        lines.append(fmt_head("Diagnosa"))
        for d in diag_items:
            lines.append(f"    * {d}")

    if single_tindakan:
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

# ============== STREAMLIT UI ==============
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
        if rec.get("cppt"):
            records.append(rec)

    if not records:
        st.warning("Tidak ada CPPT pada tanggal yang dipilih di file-file yang diupload.")
    else:
        records.sort(key=lambda r: r["cppt"]["dt"])
        outputs = [build_review(r, operator_all, i, target_date) for i, r in enumerate(records, start=1)]
        final_text = "\n\n".join(outputs)

        st.success("✅ Review selesai.")
        st.code(final_text, language="markdown")
        st.download_button("⬇️ Download review.txt", final_text.encode("utf-8"),
                           file_name="review.txt", mime="text/plain")
else:
    st.info("Pilih tanggal lalu upload HTML dari SIMRS.")
