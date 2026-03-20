"""Generate 44-part semiconductor equipment test subset (2 per manufacturer)."""

import openpyxl
from pathlib import Path

# 2 parts per manufacturer — diverse part types
PARTS = [
    # McMaster-Carr
    ("91251A197", "McMaster-Carr"),  ("92148A261", "McMaster-Carr"),
    # SMC
    ("SY3120-5LZD-M5", "SMC"),      ("CDQSB16-10D", "SMC"),
    # THK
    ("HSR15R", "THK"),               ("HSR20R", "THK"),
    # NSK
    ("6200ZZ", "NSK"),               ("6201ZZ", "NSK"),
    # Swagelok
    ("SS-400-1-4", "Swagelok"),      ("SS-600-1-4", "Swagelok"),
    # Parker
    ("2-012-N674-70", "Parker"),     ("2-013-N674-70", "Parker"),
    # Keyence
    ("FU-35FA", "Keyence"),          ("FS-N11MN", "Keyence"),
    # Omron
    ("E2E-X5ME1", "Omron"),          ("E3Z-D62", "Omron"),
    # Festo
    ("DSNU-16-25-P-A", "Festo"),     ("DSNU-16-50-P-A", "Festo"),
    # HIWIN
    ("HGH20CA", "HIWIN"),            ("MGN12C", "HIWIN"),
    # TE Connectivity
    ("1-794106-0", "TE Connectivity"), ("282834-2", "TE Connectivity"),
    # NTN
    ("6200LLB", "NTN"),              ("6201LLB", "NTN"),
    # Misumi
    ("SHCB-M4-12", "Misumi"),        ("SHCB-M5-16", "Misumi"),
    # CKD
    ("4KB110-06-B", "CKD"),          ("SSD-L-16-10", "CKD"),
    # Edwards
    ("A505-40-000", "Edwards"),      ("A505-09-000", "Edwards"),
    # VAT
    ("61532-KAGD-AKR1", "VAT"),      ("61532-KEGQ-AKR1", "VAT"),
    # Entegris
    ("H22-100-0615", "Entegris"),    ("H22-150-0615", "Entegris"),
    # Fastenal
    ("11104879", "Fastenal"),        ("11104880", "Fastenal"),
    # IKO
    ("CRB4010", "IKO"),              ("CRB5013", "IKO"),
    # Pall
    ("PLF010", "Pall"),              ("PLF020", "Pall"),
    # MKS Instruments
    ("722B13TCD2FA", "MKS Instruments"), ("627D01TDC1B", "MKS Instruments"),
    # Specialty Bolt
    ("25N150FEWS", "Specialty Bolt & Screw"), ("25N200FEWS", "Specialty Bolt & Screw"),
]

print(f"Total parts: {len(PARTS)}")
print(f"Manufacturers: {len(set(p[1] for p in PARTS))}")

output_path = Path(__file__).parent / "input" / "PartClassifierInput_44.xlsx"
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Parts"

headers = ["Part Number", "Part Name", "Manufacturer Part Number", "Manufacturer Name", "Unit of Measure"]
ws.append(headers)

for i, (mfg_pn, mfg_name) in enumerate(PARTS, 1):
    ws.append([f"TEST-{i:04d}", "", mfg_pn, mfg_name, "mm"])

wb.save(output_path)
print(f"Saved: {output_path}")
