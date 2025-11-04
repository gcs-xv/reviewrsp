import re
import io
from typing import List, Optional

import streamlit as st
from PIL import Image
try:
    import pytesseract
except ImportError:
    pytesseract = None

# ========== Helpers ==========
def format_rm_with_dots(rm_raw: str) -> str:
    digits = re.sub(r"\D", "", rm_raw or "")
    if not digits:
        return ""
    # format: 6 digit -> 2.2.2 ; 7 digit -> 1.2.2.2 ; flexible fallback
    if len(digits) == 6:
        parts = [digits[0:2], digits[2:4], digits[4:6]]
    elif len(digits) == 7:
        parts = [digits[0:1], digits[1:3], digits[3:5], digits[5:7]]
    else:
        # group by 2s
        parts = [digits[i:i+2] for i in range(0, len(digits), 2)]
    return ".".join(parts)

def format_date_ddmmyyyy(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    m = re.search(r"(\d{4})[-/\.](\d{2})[-/\.](\d{2})", s)
    if m:
        y, mo, d = m.groups()
        return f"{d}/{mo}/{y}"
    m = re.search(r"(\d{2})[-/\.](\d{2})[-/\.](\d{4})", s)
    if m:
        d, mo, y = m.groups()
        return f"{d}/{mo}/{y}"
    return s  # fallback

def normalize_key(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())

DPJP_CANONICAL = [
    "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)",
    "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K).",
    "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)",
    "drg. Carolina Stevanie, Sp.B.M.M.",
]

# buat index normalisasi (kata kunci pendek juga dikenali)
DPJP_INDEX = {normalize_key(v): v for v in DPJP_CANONICAL}
DPJP_ALIASES = {
    "ruslin": DPJP_CANONICAL[0],
    "yossyyoanitaariestiana": DPJP_CANONICAL[1],
    "yossy": DPJP_CANONICAL[1],
    "gazali": DPJP_CANONICAL[2],
    "carolinastevanie": DPJP_CANONICAL[3],
    "carolina": DPJP_CANONICAL[3],
}

def map_dpjp(raw: str) -> str:
    key = normalize_key(raw)
    # cocok exact normalisasi
    if key in DPJP_INDEX:
        return DPJP_INDEX[key]
    # alias pendek
    for k, v in DPJP_ALIASES.items():
        if k in key:
            return v
    # fallback: biarkan apa adanya (nanti user bisa pilih dari selectbox)
    return raw

def split_plan_to_items(plan_text: str) -> List[str]:
    if not plan_text:
        return []
    # ganti pemisah umum menjadi newline
    text = plan_text.replace("•", "\n").replace("·", "\n")
    text = re.sub(r"\s*[-–]\s*", "\n", text)  # strip dash bullets
    text = text.replace(",", "\n")  # sering dipisah koma
    # pecah baris, bersihkan
    items = [re.sub(r"\s+", " ", x).strip(" .") for x in text.splitlines()]
    # filter baris kosong & yang terlalu generik
    items = [i for i in items if i and not i.lower().startswith(("instruksi", "evaluasi"))]
    # dedup sambil pertahankan urutan
    seen, dedup = set(), []
    for i in items:
        k = i.lower()
        if k not in seen:
            dedup.append(i)
            seen.add(k)
    return dedup

def pick_kontrol(items: List[str]) -> Optional[str]:
    for i in items:
        if i.lower().startswith(("pro ", "pro-", "pro/")):
            return i
    return items[0] if items else None

def render_tindakan(items: List[str]) -> str:
    items = [i for i in items if i]  # clean
    if len(items) <= 1:
        return f"• Tindakan        : {items[0] if items else ''}"
    else:
        bullets = "\n".join([f"    * {i}" for i in items])
        return f"• Tindakan        :\n{bullets}"

def ocr_image_to_text(img: Image.Image) -> str:
    if pytesseract is None:
        return ""
    return pytesseract.image_to_string(img, lang="ind+eng")

def guess_fields(ocr: str) -> dict:
    guess = {
        "nama": "",
        "tgl_lahir": "",
        "rm": "",
        "telepon": "",
        "diagnosa": "",
        "plan": "",
        "dpjp_raw": "",
    }
    if not ocr:
        return guess

    lines = [l.strip() for l in ocr.splitlines() if l.strip()]

    # Nama & RM: cari baris berawalan "Pasien"
    for ln in lines:
        if re.search(r"\bPasien\b", ln, re.I):
            # contoh: "Pasien : 253385 PRICYLIA STEFINA PALIMBONG"
            m_rm = re.search(r"(\d{5,8})", ln)
            if m_rm:
                guess["rm"] = m_rm.group(1)
            # ambil sisa huruf kapital setelah angka
            m_name = re.search(r"\d+\s+([A-Z \.\-']{3,})", ln)
            if m_name:
                guess["nama"] = m_name.group(1).title()
            break

    # Tgl lahir
    m = re.search(r"(\d{4}[-/\.]\d{2}[-/\.]\d{2}|\d{2}[-/\.]\d{2}[-/\.]\d{4})", ocr)
    if m:
        guess["tgl_lahir"] = m.group(1)

    # Telepon
    m = re.search(r"(08\d{8,13})", ocr)
    if m:
        guess["telepon"] = m.group(1)

    # DPJP (Dokter/Paramedis baris)
    for i, ln in enumerate(lines):
        if "Dokter/Paramedis" in ln or "Dokter / Paramedis" in ln:
            # biasanya nama dokter ada di baris berikutnya
            if i + 1 < len(lines):
                guess["dpjp_raw"] = lines[i + 1]
            break
    # fallback: cari "drg." terdekat dengan CPPT
    if not guess["dpjp_raw"]:
        for ln in lines:
            if re.search(r"\bdrg\.", ln, re.I):
                guess["dpjp_raw"] = ln
                break

    # Diagnosa
    # cari teks setelah "Asesmen/Intervensi" atau "Objek/Diagnosis"
    diag = []
    hit = False
    for ln in lines:
        if re.search(r"(Objek/Diagnosis|Objek Diagnosa|Diagnosis)", ln, re.I):
            hit = True
            continue
        if hit:
            if re.search(r"(Asesmen/Intervensi|Plan/Monitoring|Instruksi|Evaluasi)", ln, re.I):
                break
            diag.append(ln)
    if diag:
        guess["diagnosa"] = " ".join(diag)

    # Plan/Monitoring
    plan = []
    hit = False
    for ln in lines:
        if re.search(r"Plan/Monitoring", ln, re.I):
            hit = True
            continue
        if hit:
            if re.search(r"(Instruksi|Evaluasi|CPPT|Riwayat|Tanggal|Dokter/Paramedis)", ln, re.I):
                break
            plan.append(ln)
    guess["plan"] = " ".join(plan)

    return guess

# ========== UI ==========
st.set_page_config(page_title="RSPTN Review Generator", page_icon="📝", layout="centered")
st.title("📝 RSPTN Review Generator")

st.markdown(
    "Upload **screenshot SIMRS**, cek hasil ekstraksi, koreksi jika perlu, "
    "lalu klik *Generate* untuk dapatkan review yang seragam."
)

img_file = st.file_uploader("Upload screenshot (.png/.jpg)", type=["png", "jpg", "jpeg"])

col_debug = st.checkbox("Tampilkan debug OCR & teks mentah", value=False)

with st.form("review_form"):
    if img_file:
        image = Image.open(img_file)
        st.image(image, caption="Screenshot diupload", use_column_width=True)

        ocr_text = ocr_image_to_text(image)
        g = guess_fields(ocr_text)

        nama = st.text_input("Nama", g["nama"])
        tgl_lahir = st.text_input("Tanggal lahir (yyyy-mm-dd / dd-mm-yyyy)", format_date_ddmmyyyy(g["tgl_lahir"]))
        rm = st.text_input("Nomor RM (mentah)", g["rm"])
        rm_formatted = format_rm_with_dots(rm)
        st.caption(f"RM terformat: **{rm_formatted or '—'}**")

        telepon = st.text_input("No. Telepon", g["telepon"])
        diagnosa = st.text_area("Diagnosa (utama)", g["diagnosa"], height=80)
        plan_raw = st.text_area("Plan/Monitoring (raw)", g["plan"], height=100)

        tindakan_items_default = split_plan_to_items(plan_raw)
        tindakan_items = st.experimental_data_editor(
            [{"tindakan": t} for t in (tindakan_items_default or [""])],
            num_rows="dynamic",
            use_container_width=True,
            key="tindakan_editor",
        )
        tindakan_list = [row["tindakan"].strip() for row in tindakan_items if row.get("tindakan", "").strip()]

        kontrol_auto = pick_kontrol(tindakan_list)
        kontrol = st.text_input("Kontrol (ambil otomatis item 'Pro ...' / ubah manual)", kontrol_auto or "")

        # DPJP mapping
        dpjp_guess = map_dpjp(g["dpjp_raw"])
        dpjp = st.selectbox(
            "DPJP (mapped)",
            options=["(Pilih dari daftar/biarkan teks mentah)"] + DPJP_CANONICAL,
            index=(DPJP_CANONICAL.index(dpjp_guess) + 1) if dpjp_guess in DPJP_CANONICAL else 0,
        )
        if dpjp == "(Pilih dari daftar/biarkan teks mentah)":
            dpjp = st.text_input("Atau tulis DPJP manual", value=dpjp_guess)

        operator = st.text_input("Operator (manual)", "")

        # ===== Submit =====
        submitted = st.form_submit_button("Generate Review")

        if submitted:
            # Format akhir
            lines = []
            lines.append(f"Nama            : {nama}".strip())
            lines.append(f"• Tanggal Lahir  : {format_date_ddmmyyyy(tgl_lahir)}")
            lines.append(f"• RM             : {format_rm_with_dots(rm)}")
            lines.append(f"• Diagnosa       : {diagnosa}")
            lines.append(render_tindakan(tindakan_list))
            lines.append(f"• Kontrol        : {kontrol or ''}")
            lines.append(f"• DPJP           : {dpjp}")
            lines.append(f"• No. Telp.      : {telepon}")
            lines.append(f"• Operator       : {operator}")

            review_text = "\n".join(lines)

            st.success("Review berhasil dibuat!")
            st.code(review_text, language="markdown")
            st.download_button("⬇️ Download .txt", data=review_text.encode("utf-8"),
                               file_name="review_pasien.txt", mime="text/plain")
    else:
        st.info("Silakan upload screenshot terlebih dahulu.")

    if col_debug and img_file:
        st.divider()
        st.subheader("Debug OCR")
        if pytesseract is None:
            st.warning("pytesseract belum terpasang di server. Tambahkan ke requirements.txt")
        else:
            st.text_area("Teks OCR mentah", ocr_text, height=240)

st.markdown("---")
st.caption(
    "Catatan: OCR bisa tidak sempurna. Form di atas memungkinkan koreksi cepat. "
    "DPJP dimapping otomatis ke daftar resmi; operator diisi manual."
)
