from bs4 import BeautifulSoup
import re
from datetime import datetime
from dateutil import parser as dtparser

DPJP_MAP = {
    "ruslin": "Prof. drg. Muhammad Ruslin, M.Kes., Ph.D., Sp.B.M.M., Subsp. Orthognat-D (K)",
    "yossy": "drg. Yossy Yoanita Ariestiana, M.KG., Sp.B.M.M., Subsp.Ortognat-D(K).",
    "gazali": "drg. Mohammad Gazali, MARS., Sp.B.M.M., Subsp.T.M.T.M.J(K)",
    "carolina": "drg. Carolina Stevanie, Sp.B.M.M.",
}
DPJP_CANON = list(DPJP_MAP.values())

def _norm_space(s): return re.sub(r"\s+", " ", (s or "").strip())
def _title_case_keep(s): return " ".join(w.capitalize() for w in _norm_space(s).split())
def _format_rm_dots(rm):
    d = re.sub(r"\D","", rm or "")
    if not d: return ""
    if len(d)==6: parts=[d[0:2],d[2:4],d[4:6]]
    elif len(d)==7: parts=[d[0:1],d[1:3],d[3:5],d[5:7]]
    else: parts=[d[i:i+2] for i in range(0,len(d),2)]
    return ".".join([p for p in parts if p])

def _format_date_ddmmyyyy(s):
    s = (s or "").strip()
    if not s: return ""
    try:
        # terima "2004-09-04" atau "04-09-2004" dst
        dt = dtparser.parse(s, dayfirst=False, fuzzy=True)
        return dt.strftime("%d/%m/%Y")
    except Exception:
        m = re.search(r"(\d{2})[-/.](\d{2})[-/.](\d{4})", s)
        if m: return f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
        m = re.search(r"(\d{4})[-/.](\d{2})[-/.](\d{2})", s)
        if m: return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
        return s

def _split_tindakan(text):
    # pecah berdasarkan bullet/dash/koma/baris
    t = (text or "").replace("•","\n").replace("·","\n")
    t = re.sub(r"\s*[-–]\s*","\n",t)
    t = t.replace(",", "\n")
    rows = [re.sub(r"\s+"," ", r).strip(" .") for r in t.splitlines()]
    rows = [r for r in rows if r and not r.lower().startswith(("instruksi","evaluasi"))]
    # normalisasi istilah lazim
    rep = {r"\bopg\b":"OPG X-ray", r"\bkonsultasi\b":"Konsultasi", r"\bkonsul\b":"Konsul interna"}
    out, seen = [], set()
    for r in rows:
        x = r
        for k,v in rep.items(): x = re.sub(k, v, x, flags=re.I)
        kx = x.lower()
        if kx not in seen:
            out.append(x)
            seen.add(kx)
    return out

def _pick_kontrol(items):
    for it in items:
        if it.lower().startswith(("pro ","pro-","pro")):
            return it
    return items[0] if items else ""

def _map_dpjp(raw):
    key = re.sub(r"[^a-z]","", (raw or "").lower())
    for k,v in DPJP_MAP.items():
        if k in key:
            return v
    # fallback: jika string sudah cocok salah satu canonical
    for v in DPJP_CANON:
        if re.sub(r"[^a-z]","", v.lower()) in key or key in re.sub(r"[^a-z]","", v.lower()):
            return v
    return raw or ""

def parse_simrs_html_to_review(html_text, dpjp_override=None, operator=""):
    soup = BeautifulSoup(html_text, "html.parser")

    # --- HEADER PASIEN (tabel pertama: No.RM, Nama Pasien, Tempat & Tanggal Lahir, Nomor Telepon)
    header_table = soup.select_one("table.tbl_form")
    rm = nama = tgl_lahir = telp = ""
    if header_table:
        for tr in header_table.select("tr.isi"):
            tds = tr.find_all("td")
            if len(tds) >= 3:
                label = _norm_space(tds[0].get_text())
                val   = _norm_space(tds[2].get_text())
                if re.search(r"No\.?\s*RM", label, re.I): rm = val
                elif re.search(r"Nama\s*Pasien", label, re.I): nama = val
                elif re.search(r"Tempat.*Tanggal\s*Lahir", label, re.I):
                    # format: "PAREPARE 2004-09-04" atau "- 2004-09-04"
                    m = re.search(r"(\d{4}[-/]\d{2}[-/]\d{2}|\d{2}[-/]\d{2}[-/]\d{4})", val)
                    if m: tgl_lahir = m.group(1)
                elif re.search(r"Nomor\s*Telepon", label, re.I):
                    telp = re.search(r"(08\d{8,13})", val or "") and re.search(r"(08\d{8,13})", val).group(1) or val
    # Contoh struktur header sesuai HTML SIMRS yang kamu upload.  [oai_citation:3‡SYAMSIAH.html](sediment://file_0000000019d0720da5492cf7ccec6df4)

    # --- CPPT TERBARU (cari semua nested table CPPT; pilih baris Tanggal terbaru)
    # Pola: ada baris header kolom "Tanggal | Dokter/Paramedis | Subjek/Asesmen | Objek/Diagnosis | Asesmen/Intervensi | Plan/Monitoring | ..."
    # Lalu baris data dengan Tanggal berbentuk "YYYY-MM-DD<br>HH:MM:SS"
    cppt_rows = []
    for big_tbl in soup.select("table.tbl_form"):
        inner = big_tbl.select("table")
        for t in inner:
            # cari baris data yang punya 8 kolom (seperti CPPT)
            for tr in t.select("tr.isi"):
                tds = tr.find_all("td")
                if len(tds) == 8:
                    tanggal_html = tds[0].decode_contents()
                    # Ambil tanggal & jam (pakai last if multi)
                    dts = re.findall(r"(\d{4}-\d{2}-\d{2})", tanggal_html)
                    hms = re.findall(r"(\d{2}:\d{2}:\d{2})", tanggal_html)
                    if dts:
                        dt_str = dts[-1] + (" " + hms[-1] if hms else " 00:00:00")
                        try:
                            dt_obj = dtparser.parse(dt_str)
                        except Exception:
                            continue
                        row = {
                            "dt": dt_obj,
                            "dokter": _norm_space(tds[1].get_text()),
                            "subjek": _norm_space(tds[2].get_text(separator=" ")),
                            "objek_diagnosis": _norm_space(tds[3].get_text(separator=" ")),
                            "asesmen_intervensi": _norm_space(tds[4].get_text(separator=" ")),
                            "plan": _norm_space(tds[5].get_text(separator=" ")),
                            "instruksi": _norm_space(tds[6].get_text(separator=" ")),
                            "eval": _norm_space(tds[7].get_text(separator=" ")),
                        }
                        cppt_rows.append(row)
    # Struktur kolom CPPT terlihat jelas pada file-file kamu.  [oai_citation:4‡PRISCYLIA.html](sediment://file_0000000046fc720a894780acdabf2568)  [oai_citation:5‡NIA.html](sediment://file_00000000b9a4722fb5bb30ffdb814beb)

    latest = max(cppt_rows, key=lambda r: r["dt"]) if cppt_rows else None

    # --- BANGUN FIELD REVIEW
    nama = _title_case_keep(nama)
    tgl_fmt = _format_date_ddmmyyyy(tgl_lahir)
    rm_dots = _format_rm_dots(rm)

    diagnosa = ""
    tindakan_text = ""
    if latest:
        # Paling aman: ambil “Objek/Diagnosis” sebagai Diagnosa utama kalau mengandung istilah kunci,
        # jika tidak, fallback ke “Asesmen/Intervensi”
        diag_cand = latest["objek_diagnosis"] or ""
        if not re.search(r"(tumor|malignan|malignant|gangren|impak|karies|osteosarcom|carcinoma|odontogenic|odontektomi)", diag_cand, re.I):
            diag_cand = latest["asesmen_intervensi"]
        diagnosa = diag_cand

        # Tindakan = dari Plan/Monitoring (ditambah baris dari Instruksi bila relevan)
        tindakan_text = "\n".join([latest["plan"], latest["instruksi"]]).strip()
    else:
        diagnosa = ""
        tindakan_text = ""

    tindakan_items = _split_tindakan(tindakan_text)
    kontrol = _pick_kontrol(tindakan_items)

    # DPJP: deteksi dari kolom Dokter/Paramedis di entri terbaru, lalu mapping
    dpjp_raw = latest["dokter"] if latest else ""
    dpjp = _map_dpjp(dpjp_raw)
    if dpjp_override:
        dpjp = dpjp_override

    # --- FORMAT OUTPUT SESUAI TEMPLATE-MU
    lines = []
    lines.append(f"Nama            : {nama}")
    lines.append(f"• Tanggal Lahir  : {tgl_fmt}")
    lines.append(f"• RM             : {rm_dots}")
    lines.append(f"• Diagnosa       : {diagnosa}")
    if len(tindakan_items) <= 1:
        lines.append(f"• Tindakan        : {tindakan_items[0] if tindakan_items else ''}")
    else:
        lines.append("• Tindakan        :")
        for t in tindakan_items:
            lines.append(f"    * {t}")
    lines.append(f"• Kontrol        : {kontrol}")
    lines.append(f"• DPJP           : {dpjp}")
    # Telp dari header pasien (tabel biodata)
    lines.append(f"• No. Telp.      : {telp}")
    # Operator kamu isi di UI, jadi tinggal masukkan lewat argumen
    lines.append(f"• Operator       : {operator}")

    return "\n".join(lines)
