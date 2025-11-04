import re
from typing import List, Optional

import streamlit as st
from PIL import Image, ImageOps, ImageFilter
import numpy as np

# =======================
# OCR: EasyOCR (offline)
# =======================
@st.cache_resource(show_spinner=False)
def load_easyocr_reader():
    import easyocr  # lazy import supaya cepat startup
    # Indonesian + English
    return easyocr.Reader(['id', 'en'], gpu=False)

def easyocr_image_to_text(pil_img: Image.Image) -> str:
    # Preprocess ringan supaya font SIMRS lebih kontras
    g = ImageOps.grayscale(pil_img)
    g = g.filter(ImageFilter.SHARPEN)
    arr = np.array(g)
    reader = load_easyocr_reader()
    # paragraph=True -> gabungkan baris yang berdekatan
    lines = reader.readtext(arr, detail=0, paragraph=True)
    # EasyOCR sering mengembalikan list string; gabung dengan newline
    return "\n".join([ln for ln in lines if ln.strip()])

# ==================================
# Helpers: formatting & normalization
# ==================================
def title_case_keep(s: str) -> str:
    if not s: return ""
    return " ".join(w.capitalize() for w in re.split(r"\s+", s.strip()))

def normalize_key(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())

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

def format_rm_with_dots(rm_raw: str) -> str:
    digits = re.sub(r"\D", "", rm_raw or "")
    if not digits: return ""
    if len(digits) == 6:
        parts = [digits[0:2], digits[2:4], digits[4:6]]
    elif len(digits) == 7:
        parts = [digits[0:1], digits[1:3], digits[3:5], digits[5:7]]
    else:
        parts = [digits[i:i+2] for i in range(0, len(digits), 2)]
    return ".".join([p for p in parts if p])

# ======================
# DPJP mapping (sesuai)
# ======================
DPJP_CANONICAL = [
    "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)",
    "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K).",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)",
    "drg. Carolina Stevanie, Sp.B.M.M.",
]
DPJP_ALIASES = {
    "ruslin": DPJP_CANONICAL[0],
    "yossy": DPJP_CANONICAL[1],
    "yoanita": DPJP_CANONICAL[1],
    "gazali": DPJP_CANONICAL[2],
    "carolina": DPJP_CANONICAL[3],
    "carolinastevanie": DPJP_CANONICAL[3],
}
def map_dpjp(raw: str) -> str:
    k = normalize_key(raw)
    if not k: return raw
    for kk, vv in DPJP_ALIASES.items():
        if kk in k: return vv
    for canon in DPJP_CANONICAL:
        if normalize_key(canon) in k or k in normalize_key(canon):
            return canon
    return raw

# ===============================
# Plan/Tindakan parsing utilities
# ===============================
def split_plan_to_items(plan_text: str) -> List[str]:
    if not plan_text: return []
    t = plan_text.replace("•", "\n").replace("·", "\n")
    t = re.sub(r"\s*[-–]\s*", "\n", t)
    t = t.replace(",", "\n")
    rows = [re.sub(r"\s+", " ", r).strip(" .") for r in t.splitlines()]
    rows = [r for r in rows if r and not r.lower().startswith(("instruksi","evaluasi"))]
    repl = {r"\bopg\b": "OPG X-ray", r"\bkonsul\b": "Konsul interna", r"\bkonsultasi\b":"Konsultasi"}
    out, seen = [], set()
    for r in rows:
        x = r
        for k,v in repl.items(): x = re.sub(k, v, x, flags=re.I)
        key = x.lower()
        if key not in seen:
            out.append(x)
            seen.add(key)
    return out

def pick_kontrol(items: List[str]) -> Optional[str]:
    for i in items:
        if i.lower().startswith(("pro ","pro-","pro")):
            return i
    return items[0] if items else None

# =========================
# OCR text -> field guessing
# =========================
def parse_from_ocr(txt: str) -> dict:
    g = dict(nama="", tgl_lahir="", rm="", telepon="", dpjp_raw="", diagnosa="", plan="")
    if not txt: return g
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    raw = "\n".join(lines)

    # RM (6–7 digit, sering mulai 2xxxxx)
    m = re.search(r"\b(2\d{5}|[0-9]{6,7})\b", raw)
    if m: g["rm"] = m.group(1)

    # Nama: setelah angka RM atau setelah kata "Pasien"
    m = re.search(r"(?:Pasien.*?\b(?:\d{6,7}\s+)?)?([A-Z][A-Z \.'-]{3,})", raw)
    if m:
        nm = m.group(1)
        # batasi kalau kedeteksi panjang banget
        nm = re.sub(r"\s{2,}", " ", nm).strip()
        if len(nm) > 40: nm = nm[:40]
        g["nama"] = title_case_keep(nm)

    # Tanggal lahir
    m = re.search(r"(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{4})", raw)
    if m: g["tgl_lahir"] = m.group(1)

    # Telepon
    m = re.search(r"(08\d{8,13})", raw)
    if m: g["telepon"] = m.group(1)

    # DPJP (cari baris ada "drg.")
    m = re.search(r"(drg\.[^\n]{5,})", raw, re.I)
    if m: g["dpjp_raw"] = m.group(1)

    # Diagnosa: ambil kalimat yang mengandung 'tumor|impa(k|c)si|gangren|karies|dll'
    m = re.search(r"((?:bone|tumor|malignan|malignant|impak[si]|gangren|karies|osteosarcoma)[^\n]{10,})", raw, re.I)
    if m: g["diagnosa"] = re.sub(r"\s+", " ", m.group(1)).strip()

    # Plan kasar: ambil baris yang mengandung "Pro " atau "konsul|opg|X-ray|MRI|USG|Odontektomi"
    plan_lines = []
    for ln in lines:
        if re.search(r"\b(Pro\s|konsul|opg|x[- ]?ray|mri|usg|odontektomi|biopsi)\b", ln, re.I):
            plan_lines.append(ln)
    g["plan"] = " ; ".join(plan_lines)

    return g

# ===============
# Streamlit  UI
# ===============
st.set_page_config(page_title="RSPTN Review (EasyOCR)", page_icon="📝", layout="centered")
st.title("📝 RSPTN Review Generator — EasyOCR (Gratis/Offline)")

st.caption("Tip akurasi: saat screenshot SIMRS, perbesar zoom Windows/SIMRS ke 125–150% biar font lebih besar.")

if "reviews" not in st.session_state:
    st.session_state.reviews = []

img_file = st.file_uploader("Upload screenshot SIMRS (.png/.jpg)", type=["png","jpg","jpeg"])

ocr_text = ""
if img_file:
    image = Image.open(img_file)
    st.image(image, caption="Screenshot diupload", use_column_width=True)
    with st.spinner("Membaca teks dari gambar (EasyOCR)..."):
        ocr_text = easyocr_image_to_text(image)

guess = parse_from_ocr(ocr_text) if ocr_text else dict(nama="", tgl_lahir="", rm="", telepon="", dpjp_raw="", diagnosa="", plan="")

with st.form("form_review"):
    col1, col2 = st.columns(2)
    with col1:
        nama = st.text_input("Nama", guess["nama"], placeholder="cth: Melianti")
        tgl_lahir = st.text_input("Tanggal lahir (yyyy-mm-dd / dd-mm-yyyy)", format_date_ddmmyyyy(guess["tgl_lahir"]))
        rm_raw = st.text_input("Nomor RM", guess["rm"])
        st.caption(f"RM terformat: **{format_rm_with_dots(rm_raw) or '—'}**")
        telepon = st.text_input("No. Telp", guess["telepon"])
    with col2:
        dpjp_guess = map_dpjp(guess.get("dpjp_raw",""))
        dpjp = st.selectbox("DPJP (mapping)", DPJP_CANONICAL + ["(Isi manual)"],
                            index=DPJP_CANONICAL.index(dpjp_guess) if dpjp_guess in DPJP_CANONICAL else len(DPJP_CANONICAL))
        if dpjp == "(Isi manual)":
            dpjp = st.text_input("DPJP manual", dpjp_guess)
        operator = st.text_input("Operator (manual)", "")

    diagnosa = st.text_area("Diagnosa (wajib)", guess["diagnosa"], height=140,
                            placeholder="cth: Bone tumor susp malignant ar mandibula dextra dd/ osteosarcoma")
    plan_raw = st.text_area("Plan/Monitoring (boleh paste dari OCR)", guess["plan"], height=160,
                            placeholder="- Pro Konsul Anestesi Fiber Optic, - Pro Thorax X-Ray, ...")

    tindakan_list = split_plan_to_items(plan_raw)
    kontrol_auto = pick_kontrol(tindakan_list)
    kontrol = st.text_input("Kontrol (ambil otomatis 'Pro ...' / ubah manual)", kontrol_auto or "")

    ok = st.form_submit_button("OK – Generate Review")

if ok:
    # Validasi minimal
    missing = []
    for label, val in [("Nama", nama), ("Tanggal lahir", tgl_lahir), ("RM", rm_raw),
                       ("Diagnosa", diagnosa), ("DPJP", dpjp), ("No. Telp", telepon), ("Operator", operator)]:
        if not (val or "").strip():
            missing.append(label)
    if missing:
        st.error("Field wajib belum lengkap: " + ", ".join(missing))
    else:
        out = []
        out.append(f"Nama            : {nama}")
        out.append(f"• Tanggal Lahir  : {format_date_ddmmyyyy(tgl_lahir)}")
        out.append(f"• RM             : {format_rm_with_dots(rm_raw)}")
        out.append(f"• Diagnosa       : {diagnosa}")
        if len(tindakan_list) <= 1:
            out.append(f"• Tindakan        : {tindakan_list[0] if tindakan_list else ''}")
        else:
            out.append("• Tindakan        :")
            for t in tindakan_list:
                out.append(f"    * {t}")
        out.append(f"• Kontrol        : {kontrol or ''}")
        out.append(f"• DPJP           : {dpjp}")
        out.append(f"• No. Telp.      : {telepon}")
        out.append(f"• Operator       : {operator}")

        review_text = "\n".join(out)
        st.success("✅ Review berhasil dibuat")
        st.code(review_text, language="markdown")
        st.session_state.reviews.append(review_text)

st.divider()
st.subheader("📦 Kumpulan Review")
if st.session_state.reviews:
    all_text = "\n\n".join(st.session_state.reviews)
    st.code(all_text, language="markdown")
    st.download_button("⬇️ Download semua (.txt)", all_text.encode("utf-8"),
                       file_name="review_pasien_semua.txt", mime="text/plain")

with st.expander("Lihat teks OCR mentah (debug)"):
    st.text_area("OCR (EasyOCR)", ocr_text or "(kosong)", height=220)
