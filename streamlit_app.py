import re
from typing import List, Optional

import streamlit as st
from PIL import Image, ImageOps, ImageFilter
from streamlit_cropper import st_cropper

# ========== OCR SAFE HELPERS ==========
def try_ocr(img: Image.Image) -> str:
    try:
        import pytesseract
    except Exception:
        return ""
    g = ImageOps.grayscale(img)
    g = g.filter(ImageFilter.SHARPEN)
    cfg = r"--oem 3 --psm 6"
    try:
        return pytesseract.image_to_string(g, lang="eng+ind", config=cfg)
    except Exception:
        return ""

# ========== FORMAT HELPERS ==========
def title_case_keep(s: str) -> str:
    if not s: return ""
    return " ".join(w.capitalize() for w in re.split(r"\s+", s.strip()))

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

# ========== DPJP ==========
DPJP_CANONICAL = [
    "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)",
    "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K).",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)",
    "drg. Carolina Stevanie, Sp.B.M.M.",
]
def normalize_key(s: str) -> str: return re.sub(r"[^a-z]", "", (s or "").lower())
DPJP_ALIASES = {"ruslin": DPJP_CANONICAL[0], "yossy": DPJP_CANONICAL[1],
                "gazali": DPJP_CANONICAL[2], "carolina": DPJP_CANONICAL[3],
                "carolinastevanie": DPJP_CANONICAL[3]}
def map_dpjp(raw: str) -> str:
    k = normalize_key(raw)
    for kk, vv in DPJP_ALIASES.items():
        if kk in k: return vv
    for canon in DPJP_CANONICAL:
        if normalize_key(canon) in k or k in normalize_key(canon): return canon
    return raw

# ========== TINDAKAN / PLAN ==========
def split_plan_to_items(plan_text: str) -> List[str]:
    if not plan_text: return []
    t = plan_text.replace("•","\n").replace("·","\n")
    t = re.sub(r"\s*[-–]\s*", "\n", t)
    t = t.replace(",", "\n")
    rows = [re.sub(r"\s+", " ", r).strip(" .") for r in t.splitlines()]
    rows = [r for r in rows if r and not r.lower().startswith(("instruksi","evaluasi"))]
    # normalisasi singkat
    repl = {r"\bopg\b":"OPG X-Ray", r"\bkonsul\b":"Konsul interna",
            r"\bkonsultasi\b":"Konsultasi"}
    out, seen = [], set()
    for r in rows:
        x = r
        for k,v in repl.items(): x = re.sub(k, v, x, flags=re.I)
        lk = x.lower()
        if lk not in seen: out.append(x); seen.add(lk)
    return out

def pick_kontrol(items: List[str]) -> Optional[str]:
    for i in items:
        if i.lower().startswith(("pro ", "pro-","pro")): return i
    return items[0] if items else None

# ========== APP ==========
st.set_page_config(page_title="RSPTN Review Generator", page_icon="📝", layout="centered")
st.title("📝 RSPTN Review Generator")

if "reviews" not in st.session_state:
    st.session_state.reviews = []

img_file = st.file_uploader("Upload screenshot SIMRS (.png/.jpg)", type=["png","jpg","jpeg"])
img = Image.open(img_file) if img_file else None
if img:
    st.image(img, caption="Screenshot diupload", use_column_width=True)

st.markdown("#### 🔎 OCR (opsional, gunakan crop per-bagian)")

colA, colB = st.columns(2)

with colA:
    st.caption("Crop HEADER (Nama, RM, Tgl lahir, Telp)")
    if img:
        box_head = st_cropper(img, realtime_update=True, box_color='#00b4d8', aspect_ratio=None, return_type="box")
        header_crop = img.crop((box_head['left'], box_head['top'],
                                box_head['left']+box_head['width'], box_head['top']+box_head['height']))
        ocr_header = try_ocr(header_crop)
        st.text_area("OCR Header", ocr_header, height=120)
    else:
        ocr_header = ""

with colB:
    st.caption("Crop CPPT kolom DIAGNOSA (atau Asesmen/Intervensi)")
    if img:
        box_diag = st_cropper(img, realtime_update=True, box_color='#52b788', aspect_ratio=None, return_type="box", key="diag")
        diag_crop = img.crop((box_diag['left'], box_diag['top'],
                              box_diag['left']+box_diag['width'], box_diag['top']+box_diag['height']))
        ocr_diag = try_ocr(diag_crop)
        st.text_area("OCR Diagnosa", ocr_diag, height=120)
    else:
        ocr_diag = ""

st.caption("Crop CPPT kolom PLAN/MONITORING (tindakan/kontrol)")
if img:
    box_plan = st_cropper(img, realtime_update=True, box_color='#ff6b6b', aspect_ratio=None, return_type="box", key="plan")
    plan_crop = img.crop((box_plan['left'], box_plan['top'],
                          box_plan['left']+box_plan['width'], box_plan['top']+box_plan['height']))
    ocr_plan = try_ocr(plan_crop)
    st.text_area("OCR Plan", ocr_plan, height=120)
else:
    ocr_plan = ""

# ====== GUESS dari OCR TERARAH ======
guess_nama = ""
guess_rm = ""
guess_tgl = ""
guess_telp = ""

if ocr_header:
    # contoh header baris: "Pasien : 244617 MELIANTI" dsb
    mrm = re.search(r"\b(2\d{5}|[0-9]{6,7})\b", ocr_header)  # RM 6-7 digit, biasanya diawali 2
    if mrm: guess_rm = mrm.group(1)
    # nama = huruf setelah RM
    mname = re.search(r"\b(?:Pasien|PASIEN)?\b.*?(?:\d{6,7}\s+)([A-Z][A-Z \.'-]{2,})", ocr_header, re.I)
    if mname: guess_nama = title_case_keep(mname.group(1))
    # tgl lahir & telp
    mt = re.search(r"(\d{4}[-/.]\d{2}[-/.]\d{2}|\d{2}[-/.]\d{2}[-/.]\d{4})", ocr_header)
    if mt: guess_tgl = mt.group(1)
    mtlp = re.search(r"(08\d{8,13})", ocr_header)
    if mtlp: guess_telp = mtlp.group(1)

guess_diag = re.sub(r"\s+", " ", ocr_diag).strip()
guess_plan = re.sub(r"\s+", " ", ocr_plan).strip()

st.markdown("### ✍️ Koreksi / Lengkapi (wajib lengkap)")
with st.form("frm"):
    col1, col2 = st.columns(2)
    with col1:
        nama = st.text_input("Nama", guess_nama, placeholder="contoh: Melianti")
        tgl_lahir = st.text_input("Tanggal lahir (yyyy-mm-dd / dd-mm-yyyy)", format_date_ddmmyyyy(guess_tgl))
        rm_raw = st.text_input("Nomor RM (mentah)", guess_rm)
        st.caption(f"RM terformat: **{format_rm_with_dots(rm_raw) or '—'}**")
        telepon = st.text_input("No. Telp", guess_telp)
    with col2:
        dpjp_sel = st.selectbox("DPJP", DPJP_CANONICAL + ["(Isi manual)"])
        dpjp = dpjp_sel if dpjp_sel != "(Isi manual)" else st.text_input("DPJP manual/mapping", "")

        operator = st.text_input("Operator (manual)", "")

    diagnosa = st.text_area("Diagnosa (wajib)", guess_diag, height=140,
                            placeholder="contoh: Bone tumor susp malignant ar mandibula dextra dd/ osteosarcoma")
    plan_raw = st.text_area("Plan/Monitoring (boleh dari OCR Plan)", guess_plan, height=160,
                            placeholder="- Pro Konsul Anestesi Fiber Optic, - Pro Thorax X-Ray, ...")

    # pecah tindakan dari plan
    tindakan_list = split_plan_to_items(plan_raw)
    kontrol_auto = pick_kontrol(tindakan_list)
    kontrol = st.text_input("Kontrol (pilih yang 'Pro ...' / ubah manual)", kontrol_auto or "")

    ok = st.form_submit_button("OK – Generate Review")

if ok:
    # VALIDASI minimal
    missing = []
    if not nama: missing.append("Nama")
    if not tgl_lahir: missing.append("Tanggal lahir")
    if not rm_raw: missing.append("RM")
    if not diagnosa: missing.append("Diagnosa")
    if not dpjp: missing.append("DPJP")
    if not telepon: missing.append("No. Telp")
    if not operator: missing.append("Operator")
    if missing:
        st.error("Field wajib belum lengkap: " + ", ".join(missing))
    else:
        lines = []
        lines.append(f"Nama            : {nama}".strip())
        lines.append(f"• Tanggal Lahir  : {format_date_ddmmyyyy(tgl_lahir)}")
        lines.append(f"• RM             : {format_rm_with_dots(rm_raw)}")
        lines.append(f"• Diagnosa       : {diagnosa}")
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
        st.success("✅ Review berhasil dibuat")
        st.code(review, language="markdown")
        st.session_state.reviews.append(review)

st.divider()
st.subheader("📦 Kumpulan Review (multi pasien)")
if st.session_state.reviews:
    all_text = "\n\n".join(st.session_state.reviews)
    st.code(all_text, language="markdown")
    st.download_button("⬇️ Download semua review (.txt)", data=all_text.encode("utf-8"),
                       file_name="review_pasien_semua.txt", mime="text/plain")
else:
    st.caption("Belum ada review. Generate dulu.")
