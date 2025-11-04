import re
from typing import List, Optional

import streamlit as st
from PIL import Image, ImageOps, ImageFilter

# ====== TRY OCR (safe fallback) ======
def ocr_image_to_text(img: Image.Image) -> str:
    try:
        import pytesseract
    except Exception:
        return ""
    # Preprocess: grayscale + adaptive threshold + sharpen
    g = ImageOps.grayscale(img)
    g = g.filter(ImageFilter.SHARPEN)
    # coba threshold ringan untuk font kecil
    try:
        g = ImageOps.invert(ImageOps.autocontrast(g.point(lambda x: 0 if x < 160 else 255)))
    except Exception:
        pass
    cfg = r"--oem 3 --psm 6"
    try:
        txt = pytesseract.image_to_string(g, lang="eng+ind", config=cfg)
    except Exception:
        txt = ""
    return txt

# ====== UTIL ======
def title_case_keep(s: str) -> str:
    if not s: return ""
    return " ".join(w.capitalize() for w in re.split(r"\s+", s.strip()))

def normalize_key(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())

def format_rm_with_dots(rm_raw: str) -> str:
    digits = re.sub(r"\D", "", rm_raw or "")
    if not digits:
        return ""
    if len(digits) == 6:
        parts = [digits[0:2], digits[2:4], digits[4:6]]
    elif len(digits) == 7:
        parts = [digits[0:1], digits[1:3], digits[3:5], digits[5:7]]
    else:
        parts = [digits[i:i+2] for i in range(0, len(digits), 2)]
    return ".".join([p for p in parts if p])

def format_date_ddmmyyyy(s: str) -> str:
    if not s: return ""
    s = s.strip()
    m = re.search(r"(\d{4})[-/.](\d{2})[-/.](\d{2})", s)
    if m:
        y, mo, d = m.groups(); return f"{d}/{mo}/{y}"
    m = re.search(r"(\d{2})[-/.](\d{2})[-/.](\d{4})", s)
    if m:
        d, mo, y = m.groups(); return f"{d}/{mo}/{y}"
    return s

DPJP_CANONICAL = [
    "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)",
    "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K).",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)",
    "drg. Carolina Stevanie, Sp.B.M.M.",
]
DPJP_ALIASES = {
    "ruslin": DPJP_CANONICAL[0],
    "yossy": DPJP_CANONICAL[1],
    "yoanitaar": DPJP_CANONICAL[1],
    "gazali": DPJP_CANONICAL[2],
    "carolina": DPJP_CANONICAL[3],
    "carolinastevanie": DPJP_CANONICAL[3],
}
def map_dpjp(raw: str) -> str:
    key = normalize_key(raw)
    if not key: return ""
    for k, v in DPJP_ALIASES.items():
        if k in key: return v
    # coba cocokkan nama belakang
    for canon in DPJP_CANONICAL:
        if any(p in key for p in normalize_key(canon).split()):
            return canon
    return raw

def split_plan_to_items(plan_text: str) -> List[str]:
    if not plan_text: return []
    t = plan_text
    t = t.replace("•", "\n").replace("·", "\n")
    t = re.sub(r"\s*[-–•]\s*", "\n", t)
    t = t.replace(",", "\n")
    rows = [re.sub(r"\s+", " ", r).strip(" .") for r in t.splitlines()]
    rows = [r for r in rows if r and not r.lower().startswith(("instruksi", "evaluasi"))]
    # Normalisasi frasa umum
    rep = {
        r"\bopg\b": "OPG X-ray",
        r"\bkonsul\b": "Konsul interna",
        r"\bkonsultasi\b": "Konsultasi",
        r"\bodontektomi\b": "Odontektomi",
    }
    norm = []
    seen = set()
    for r in rows:
        x = r
        for k, v in rep.items():
            x = re.sub(k, v, x, flags=re.I)
        kx = x.lower()
        if kx not in seen:
            norm.append(x)
            seen.add(kx)
    return norm

def pick_kontrol(items: List[str]) -> Optional[str]:
    for i in items:
        if i.lower().startswith(("pro ", "pro-", "pro")):
            return i
    return items[0] if items else None

def render_tindakan(items: List[str]) -> str:
    items = [i for i in items if i]
    if len(items) <= 1:
        return f"• Tindakan        : {items[0] if items else ''}"
    return "• Tindakan        :\n" + "\n".join([f"    * {i}" for i in items])

# ====== PARSER OCR ======
def parse_from_ocr(txt: str) -> dict:
    g = dict(nama="", tgl_lahir="", rm="", telepon="", dpjp_raw="", diagnosa="", plan="")
    if not txt: return g
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    raw = "\n".join(lines)

    # RM: biasanya deretan 6-7 digit dekat kata "Pasien"
    m = re.search(r"\bPasien\b[^0-9]*([0-9]{6,8})", raw, re.I)
    if not m:
        m = re.search(r"\bNo\.?\s*RM\b[^0-9]*([0-9]{6,8})", raw, re.I)
    if m: g["rm"] = m.group(1)

    # Nama: setelah nomor RM di baris pasien
    m = re.search(r"\bPasien\b.*?(?:\d{6,8}\s*)([A-Z][A-Z \.'-]{2,})", raw, re.I)
    if m: g["nama"] = title_case_keep(m.group(1))

    # Tanggal lahir
    m = re.search(r"(?:Tgl\.?\s*Lahir|Tanggal\s*Lahir|Tgl\.?\s*Lahir).*?(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{4})", raw, re.I)
    if not m:
        m = re.search(r"(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{4})", raw)
    if m: g["tgl_lahir"] = m.group(1)

    # Telepon
    m = re.search(r"(08\d{8,13})", raw)
    if m: g["telepon"] = m.group(1)

    # DPJP (baris Dokter/Paramedis)
    for i, ln in enumerate(lines):
        if re.search(r"Dokter/?Paramedis", ln, re.I):
            if i+1 < len(lines): g["dpjp_raw"] = lines[i+1]
            break
    if not g["dpjp_raw"]:
        m = re.search(r"(drg\.[^\n]{5,})", raw, re.I)
        if m: g["dpjp_raw"] = m.group(1)

    # Diagnosis: blok setelah "Asesmen/Intervensi" atau "Objek/Diagnosis"
    def grab_block(start_pat, stop_pats):
        take = False; out=[]
        for ln in lines:
            if re.search(start_pat, ln, re.I): take=True; continue
            if take and any(re.search(p, ln, re.I) for p in stop_pats): break
            if take: out.append(ln)
        return " ".join(out).strip()

    diagnosa = grab_block(r"(Objek/Diagnosis|Objek Diagnosa)", [r"Asesmen/Intervensi", r"Plan/Monitoring", r"Instruksi", r"Evaluasi", r"CPPT"])
    if not diagnosa:
        diagnosa = grab_block(r"Asesmen/Intervensi", [r"Plan/Monitoring", r"Instruksi", r"Evaluasi", r"CPPT"])
    g["diagnosa"] = re.sub(r"\s+", " ", diagnosa)

    plan = grab_block(r"Plan/Monitoring", [r"Instruksi", r"Evaluasi", r"CPPT", r"Riwayat", r"Tanggal", r"Dokter/Paramedis"])
    g["plan"] = re.sub(r"\s+", " ", plan)

    return g

# ====== STREAMLIT UI ======
st.set_page_config(page_title="RSPTN Review Generator", page_icon="📝", layout="centered")
st.title("📝 RSPTN Review Generator")

# kumpulan review multi pasien
if "reviews" not in st.session_state:
    st.session_state.reviews = []

uploaded = st.file_uploader("Upload screenshot SIMRS (.png/.jpg)", type=["png","jpg","jpeg"])
raw_ocr = ""
if uploaded:
    img = Image.open(uploaded)
    st.image(img, caption="Screenshot diupload", use_column_width=True)
    raw_ocr = ocr_image_to_text(img)

guess = parse_from_ocr(raw_ocr) if raw_ocr else dict(nama="", tgl_lahir="", rm="", telepon="", dpjp_raw="", diagnosa="", plan="")

with st.form("frm"):
    col1, col2 = st.columns(2)
    with col1:
        nama = st.text_input("Nama", guess["nama"])
        tgl_lahir = st.text_input("Tanggal Lahir (yyyy-mm-dd / dd-mm-yyyy)", format_date_ddmmyyyy(guess["tgl_lahir"]))
        rm_raw = st.text_input("Nomor RM (mentah)", guess["rm"])
        rm_fmt = format_rm_with_dots(rm_raw)
        st.caption(f"RM terformat: **{rm_fmt or '—'}**")
        telepon = st.text_input("No. Telp", guess["telepon"])
    with col2:
        # DPJP mapping
        dpjp_guess = map_dpjp(guess.get("dpjp_raw",""))
        dpjp_choice = st.selectbox("DPJP (mapping)", ["(Pilih)"] + DPJP_CANONICAL,
                                   index=(DPJP_CANONICAL.index(dpjp_guess)+1) if dpjp_guess in DPJP_CANONICAL else 0)
        dpjp = dpjp_choice if dpjp_choice != "(Pilih)" else st.text_input("Atau isi DPJP manual", dpjp_guess)
        operator = st.text_input("Operator (manual)", "")

    diagnosa = st.text_area("Diagnosa (utama)", guess["diagnosa"], height=140)
    plan_raw = st.text_area("Plan/Monitoring (raw)", guess["plan"], height=160)

    # daftar tindakan editable
    default_items = split_plan_to_items(plan_raw) or [""]
    data_rows = [{"Tindakan": t} for t in default_items]
    edited = st.data_editor(data_rows, num_rows="dynamic", use_container_width=True, key="tindak")
    tindakan_list = [r["Tindakan"].strip() for r in edited if r.get("Tindakan","").strip()]
    kontrol_auto = pick_kontrol(tindakan_list)
    kontrol = st.text_input("Kontrol (ambil otomatis item 'Pro ...' / ubah manual)", kontrol_auto or "")

    # === Submit button SELALU ADA ===
    ok = st.form_submit_button("OK – Generate Review")

# hasil
if ok:
    lines = []
    lines.append(f"Nama            : {nama}".strip())
    lines.append(f"• Tanggal Lahir  : {format_date_ddmmyyyy(tgl_lahir)}")
    lines.append(f"• RM             : {format_rm_with_dots(rm_raw)}")
    lines.append(f"• Diagnosa       : {diagnosa}")
    # aturan bullet
    if len(tindakan_list) <= 1:
        lines.append(f"• Tindakan        : {tindakan_list[0] if tindakan_list else ''}")
    else:
        lines.append("• Tindakan        :")
        for t in tindakan_list:
            lines.append(f"    * {t}")
    lines.append(f"• Kontrol        : {kontrol or ''}")
    lines.append(f"• DPJP           : {dpjp}")
    lines.append(f"• No. Telp.      : {telepon}")
    lines.append(f"• Operator       : {operator}")

    review = "\n".join(lines)
    st.success("Review dibuat.")
    st.code(review, language="markdown")

    # simpan ke list multi pasien
    st.session_state.reviews.append(review)

st.divider()
st.subheader("📦 Kumpulan Review (multi pasien)")
if st.session_state.reviews:
    all_text = "\n\n".join(st.session_state.reviews)
    st.code(all_text, language="markdown")
    st.download_button("⬇️ Download semua review (.txt)", data=all_text.encode("utf-8"),
                       file_name="review_pasien_semua.txt", mime="text/plain")
else:
    st.caption("Belum ada review yang disimpan. Generate dulu lalu otomatis masuk ke sini.")

# Debug optional
with st.expander("Debug OCR (opsional)"):
    if raw_ocr:
        st.text_area("Teks OCR mentah", raw_ocr, height=260)
    else:
        st.caption("OCR kosong atau Tesseract belum terpasang.")
