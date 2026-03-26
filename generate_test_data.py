"""
Generate 400-part semiconductor equipment test input Excel.
20+ manufacturers, real OEM part numbers used in semiconductor fab equipment.
"""

import openpyxl
from pathlib import Path

# Real part numbers from semiconductor equipment supply chains
# Format: (Manufacturer Part Number, Manufacturer Name)
PARTS = []

# 1. McMaster-Carr (fasteners, washers, O-rings) — 25 parts
mcmaster = [
    ("91251A197", "McMaster-Carr"), ("91251A211", "McMaster-Carr"),
    ("91251A446", "McMaster-Carr"), ("91251A540", "McMaster-Carr"),
    ("92196A541", "McMaster-Carr"), ("92196A545", "McMaster-Carr"),
    ("92196A110", "McMaster-Carr"), ("92196A113", "McMaster-Carr"),
    ("92148A261", "McMaster-Carr"), ("92148A112", "McMaster-Carr"),
    ("92148A160", "McMaster-Carr"), ("92148A175", "McMaster-Carr"),
    ("98449A515", "McMaster-Carr"), ("98449A525", "McMaster-Carr"),
    ("90585A140", "McMaster-Carr"), ("90585A150", "McMaster-Carr"),
    ("91828A211", "McMaster-Carr"), ("91828A225", "McMaster-Carr"),
    ("9452K111", "McMaster-Carr"),  ("9452K115", "McMaster-Carr"),
    ("93827A211", "McMaster-Carr"), ("93827A220", "McMaster-Carr"),
    ("92855A416", "McMaster-Carr"), ("92855A521", "McMaster-Carr"),
    ("94804A325", "McMaster-Carr"),
]

# 2. SMC (pneumatic valves, cylinders, fittings) — 25 parts
smc = [
    ("SY3120-5LZD-M5", "SMC"), ("SY3120-5LZD-C4", "SMC"),
    ("SY3220-5LZD-M5", "SMC"), ("SY5120-5LZD-01", "SMC"),
    ("SY5220-5LZD-01", "SMC"), ("SY7120-5LZD-02", "SMC"),
    ("CDQSB16-10D", "SMC"),    ("CDQSB16-25D", "SMC"),
    ("CDQSB20-10D", "SMC"),    ("CDQSB20-25D", "SMC"),
    ("CDQ2B16-10DZ", "SMC"),   ("CDQ2B16-25DZ", "SMC"),
    ("CDQ2B20-10DZ", "SMC"),   ("CDQ2B20-25DZ", "SMC"),
    ("KQ2H04-M5A", "SMC"),     ("KQ2H06-M5A", "SMC"),
    ("KQ2H04-01AS", "SMC"),    ("KQ2H06-01AS", "SMC"),
    ("KQ2L04-M5A", "SMC"),     ("KQ2L06-M5A", "SMC"),
    ("VQZ115-5L1-M5", "SMC"),  ("VQZ215-5L1-M5", "SMC"),
    ("ISE30A-01-N", "SMC"),    ("ISE30A-C6L-N", "SMC"),
    ("ITV1030-31N2L4", "SMC"),
]

# 3. THK (linear guides, ball screws) — 20 parts
thk = [
    ("HSR15R", "THK"),  ("HSR20R", "THK"),  ("HSR25R", "THK"),
    ("HSR30R", "THK"),  ("HSR35R", "THK"),  ("HSR15A", "THK"),
    ("HSR20A", "THK"),  ("HSR25A", "THK"),  ("SHS15C", "THK"),
    ("SHS20C", "THK"),  ("SHS25C", "THK"),  ("SHS15V", "THK"),
    ("SHS20V", "THK"),  ("SSR15XW", "THK"), ("SSR20XW", "THK"),
    ("RSR12WZM", "THK"), ("RSR15WZM", "THK"),
    ("BNK1402-3RRG0+270LC5A", "THK"), ("BNK1404-3RRG0+400LC5A", "THK"),
    ("BNK1010-3RRG0+200LC5A", "THK"),
]

# 4. NSK (bearings) — 20 parts
nsk = [
    ("6200ZZ", "NSK"),   ("6201ZZ", "NSK"),   ("6202ZZ", "NSK"),
    ("6203ZZ", "NSK"),   ("6204ZZ", "NSK"),   ("6205ZZ", "NSK"),
    ("6200DDU", "NSK"),  ("6201DDU", "NSK"),  ("6202DDU", "NSK"),
    ("7200BECBP", "NSK"), ("7201BECBP", "NSK"), ("7202BECBP", "NSK"),
    ("7200A5TRSULP4", "NSK"), ("7201A5TRSULP4", "NSK"),
    ("6800ZZ", "NSK"),   ("6801ZZ", "NSK"),   ("6802ZZ", "NSK"),
    ("6900ZZ", "NSK"),   ("6901ZZ", "NSK"),   ("6902ZZ", "NSK"),
]

# 5. Swagelok (tube fittings, valves) — 20 parts
swagelok = [
    ("SS-400-1-4", "Swagelok"),  ("SS-400-1-2", "Swagelok"),
    ("SS-400-1-8", "Swagelok"),  ("SS-400-6", "Swagelok"),
    ("SS-600-1-4", "Swagelok"),  ("SS-600-1-6", "Swagelok"),
    ("SS-600-3", "Swagelok"),    ("SS-600-6", "Swagelok"),
    ("SS-810-1-8", "Swagelok"),  ("SS-810-3", "Swagelok"),
    ("SS-4-VCR-1", "Swagelok"),  ("SS-4-VCR-3", "Swagelok"),
    ("SS-8-VCR-1", "Swagelok"),  ("SS-8-VCR-6", "Swagelok"),
    ("SS-43GS4", "Swagelok"),    ("SS-43GS6", "Swagelok"),
    ("SS-42GS4", "Swagelok"),    ("SS-42GS6", "Swagelok"),
    ("SS-4-TA-1-4", "Swagelok"), ("SS-6-TA-1-4", "Swagelok"),
]

# 6. Parker Hannifin (O-rings, seals, fittings) — 20 parts
parker = [
    ("2-012-N674-70", "Parker"),   ("2-013-N674-70", "Parker"),
    ("2-014-N674-70", "Parker"),   ("2-015-N674-70", "Parker"),
    ("2-016-N674-70", "Parker"),   ("2-110-N674-70", "Parker"),
    ("2-111-N674-70", "Parker"),   ("2-112-N674-70", "Parker"),
    ("2-012-S353-70", "Parker"),   ("2-013-S353-70", "Parker"),
    ("2-014-S353-70", "Parker"),   ("2-015-S353-70", "Parker"),
    ("2-012-V884-75", "Parker"),   ("2-013-V884-75", "Parker"),
    ("4-012-N674-70", "Parker"),   ("4-013-N674-70", "Parker"),
    ("2-210-N674-70", "Parker"),   ("2-211-N674-70", "Parker"),
    ("2-212-N674-70", "Parker"),   ("2-213-N674-70", "Parker"),
]

# 7. Keyence (sensors, fiber optics) — 20 parts
keyence = [
    ("FU-35FA", "Keyence"),   ("FU-35FZ", "Keyence"),
    ("FU-35TZ", "Keyence"),   ("FU-77", "Keyence"),
    ("FU-77V", "Keyence"),    ("FU-67V", "Keyence"),
    ("FS-N11MN", "Keyence"),  ("FS-N12MN", "Keyence"),
    ("FS-N41N", "Keyence"),   ("FS-N42N", "Keyence"),
    ("LR-ZB250CP", "Keyence"), ("LR-ZB100CN", "Keyence"),
    ("GV-21P", "Keyence"),    ("GV-22P", "Keyence"),
    ("IL-030", "Keyence"),    ("IL-065", "Keyence"),
    ("IL-100", "Keyence"),    ("IL-300", "Keyence"),
    ("PZ-G41N", "Keyence"),   ("PZ-G51N", "Keyence"),
]

# 8. Omron (sensors, relays) — 20 parts
omron = [
    ("E2E-X5ME1", "Omron"),    ("E2E-X2ME1", "Omron"),
    ("E2E-X3D1-M1G", "Omron"), ("E2E-X5D1-M1G", "Omron"),
    ("E2E-X8MD1", "Omron"),    ("E2E-X10ME1", "Omron"),
    ("E3Z-D62", "Omron"),      ("E3Z-D82", "Omron"),
    ("E3Z-T61", "Omron"),      ("E3Z-T81", "Omron"),
    ("D4NS-1AF", "Omron"),     ("D4NS-2AF", "Omron"),
    ("G3NA-210B", "Omron"),    ("G3NA-220B", "Omron"),
    ("H3Y-2-C", "Omron"),      ("H3Y-4-C", "Omron"),
    ("MY2N-GS", "Omron"),      ("MY4N-GS", "Omron"),
    ("E2S-Q13", "Omron"),      ("E2S-Q23", "Omron"),
]

# 9. Festo (pneumatic cylinders, valves) — 20 parts
festo = [
    ("DSNU-16-25-P-A", "Festo"), ("DSNU-16-50-P-A", "Festo"),
    ("DSNU-20-25-P-A", "Festo"), ("DSNU-20-50-P-A", "Festo"),
    ("DSNU-25-25-P-A", "Festo"), ("DSNU-25-50-P-A", "Festo"),
    ("ADN-16-25-I-P-A", "Festo"), ("ADN-16-50-I-P-A", "Festo"),
    ("ADN-20-25-I-P-A", "Festo"), ("ADN-20-50-I-P-A", "Festo"),
    ("VUVG-L10-M52-MT-M5-1P3", "Festo"),
    ("VUVG-L10-M52-MT-M3-1P3", "Festo"),
    ("CPE14-M1BH-5L-1/8", "Festo"), ("CPE14-M1BH-5J-1/8", "Festo"),
    ("QSM-M5-4", "Festo"),     ("QSM-M5-6", "Festo"),
    ("QSL-6", "Festo"),        ("QSL-8", "Festo"),
    ("GRLA-M5-QS-4-D", "Festo"), ("GRLA-M5-QS-6-D", "Festo"),
]

# 10. HIWIN (linear guides, ball screws) — 20 parts
hiwin = [
    ("HGH15CA", "HIWIN"),  ("HGH20CA", "HIWIN"),  ("HGH25CA", "HIWIN"),
    ("HGH30CA", "HIWIN"),  ("HGH35CA", "HIWIN"),
    ("HGW15CC", "HIWIN"),  ("HGW20CC", "HIWIN"),  ("HGW25CC", "HIWIN"),
    ("HGW30CC", "HIWIN"),  ("HGW35CC", "HIWIN"),
    ("EGH15CA", "HIWIN"),  ("EGH20CA", "HIWIN"),  ("EGH25CA", "HIWIN"),
    ("MGN7C", "HIWIN"),    ("MGN9C", "HIWIN"),     ("MGN12C", "HIWIN"),
    ("MGN15C", "HIWIN"),   ("MGW9C", "HIWIN"),     ("MGW12C", "HIWIN"),
    ("MGW15C", "HIWIN"),
]

# 11. TE Connectivity (connectors) — 20 parts
te = [
    ("1-794106-0", "TE Connectivity"), ("1-794107-0", "TE Connectivity"),
    ("1-794108-0", "TE Connectivity"), ("1-794109-0", "TE Connectivity"),
    ("1-794110-0", "TE Connectivity"),
    ("1-776087-0", "TE Connectivity"), ("1-776088-0", "TE Connectivity"),
    ("1-776089-0", "TE Connectivity"),
    ("282834-2", "TE Connectivity"),   ("282834-3", "TE Connectivity"),
    ("282834-4", "TE Connectivity"),   ("282834-5", "TE Connectivity"),
    ("640456-3", "TE Connectivity"),   ("640456-4", "TE Connectivity"),
    ("640456-5", "TE Connectivity"),   ("640456-6", "TE Connectivity"),
    ("1-480424-0", "TE Connectivity"), ("1-480425-0", "TE Connectivity"),
    ("350547-1", "TE Connectivity"),   ("350547-2", "TE Connectivity"),
]

# 12. NTN (bearings) — 15 parts
ntn = [
    ("6200LLB", "NTN"),  ("6201LLB", "NTN"),  ("6202LLB", "NTN"),
    ("6203LLB", "NTN"),  ("6204LLB", "NTN"),  ("6205LLB", "NTN"),
    ("6200LLU", "NTN"),  ("6201LLU", "NTN"),  ("6202LLU", "NTN"),
    ("6800LLB", "NTN"),  ("6801LLB", "NTN"),  ("6802LLB", "NTN"),
    ("7200B", "NTN"),    ("7201B", "NTN"),     ("7202B", "NTN"),
]

# 13. Misumi (fasteners, mechanical components) — 20 parts
misumi = [
    ("SHCB-M3-8", "Misumi"),   ("SHCB-M3-10", "Misumi"),
    ("SHCB-M4-10", "Misumi"),  ("SHCB-M4-12", "Misumi"),
    ("SHCB-M5-10", "Misumi"),  ("SHCB-M5-16", "Misumi"),
    ("SHCB-M6-12", "Misumi"),  ("SHCB-M6-16", "Misumi"),
    ("SHCB-M8-16", "Misumi"),  ("SHCB-M8-20", "Misumi"),
    ("SSHRS8-40", "Misumi"),   ("SSHRS10-50", "Misumi"),
    ("SSHRS12-60", "Misumi"),  ("SSHRS16-80", "Misumi"),
    ("HFSF5-2040", "Misumi"),  ("HFSF5-2060", "Misumi"),
    ("HFSF5-2080", "Misumi"),  ("HFSF5-20100", "Misumi"),
    ("HBLFSN5", "Misumi"),     ("HBLFSN6", "Misumi"),
]

# 14. CKD (pneumatic valves, cylinders) — 15 parts
ckd = [
    ("4KB110-06-B", "CKD"),    ("4KB210-06-B", "CKD"),
    ("4KB310-08-B", "CKD"),    ("4KB410-10-B", "CKD"),
    ("SSD-L-16-10", "CKD"),    ("SSD-L-16-25", "CKD"),
    ("SSD-L-20-10", "CKD"),    ("SSD-L-20-25", "CKD"),
    ("AMD21-8BUS", "CKD"),     ("AMD21-10BUS", "CKD"),
    ("AMD31-10BUS", "CKD"),    ("AMD31-12BUS", "CKD"),
    ("SCM-00-16B-25", "CKD"),  ("SCM-00-20B-25", "CKD"),
    ("SCM-00-25B-50", "CKD"),
]

# 15. Edwards Vacuum — 15 parts
edwards = [
    ("A505-40-000", "Edwards"),   ("A505-09-000", "Edwards"),
    ("A505-12-000", "Edwards"),   ("A505-14-000", "Edwards"),
    ("H14307000", "Edwards"),     ("H14407000", "Edwards"),
    ("A462-40-000", "Edwards"),   ("A462-80-000", "Edwards"),
    ("A463-40-000", "Edwards"),   ("A463-80-000", "Edwards"),
    ("A373-24-958", "Edwards"),   ("A373-26-958", "Edwards"),
    ("A100-04-000", "Edwards"),   ("A100-06-000", "Edwards"),
    ("A100-12-000", "Edwards"),
]

# 16. VAT (vacuum valves) — 15 parts
vat = [
    ("61532-KAGD-AKR1", "VAT"),  ("61532-KEGQ-AKR1", "VAT"),
    ("61534-KAGD-AKR1", "VAT"),  ("61536-KAGD-AKR1", "VAT"),
    ("62032-KAGD-AAR1", "VAT"),  ("62034-KAGD-AAR1", "VAT"),
    ("62036-KAGD-AAR1", "VAT"),
    ("01032-KA11-AKR1", "VAT"),  ("01034-KA11-AKR1", "VAT"),
    ("26428-KA11-BMJ1", "VAT"),  ("26432-KA11-BMJ1", "VAT"),
    ("26428-KA21-BMJ1", "VAT"),
    ("F-2002-D-001", "VAT"),     ("F-2004-D-001", "VAT"),
    ("F-2006-D-001", "VAT"),
]

# 17. Entegris (wafer handling, fluid management) — 15 parts
entegris = [
    ("H22-100-0615", "Entegris"), ("H22-150-0615", "Entegris"),
    ("H22-200-0615", "Entegris"),
    ("H50-100-0615", "Entegris"), ("H50-150-0615", "Entegris"),
    ("H50-200-0615", "Entegris"),
    ("NT20-5-100-B16SS", "Entegris"), ("NT20-5-100-B36SS", "Entegris"),
    ("NT20-5-100-N36SS", "Entegris"),
    ("PFP-050-H01-A", "Entegris"), ("PFP-100-H01-A", "Entegris"),
    ("PFP-200-H01-A", "Entegris"),
    ("WGFG01SRJ", "Entegris"),   ("WGFG02SRJ", "Entegris"),
    ("WGFG03SRJ", "Entegris"),
]

# 18. Fastenal (fasteners) — 20 parts
fastenal = [
    ("11104879", "Fastenal"),  ("11104880", "Fastenal"),
    ("11104881", "Fastenal"),  ("11104882", "Fastenal"),
    ("11104883", "Fastenal"),  ("11104884", "Fastenal"),
    ("11104885", "Fastenal"),  ("11104886", "Fastenal"),
    ("11104887", "Fastenal"),  ("11104888", "Fastenal"),
    ("11129753", "Fastenal"),  ("11129754", "Fastenal"),
    ("11129755", "Fastenal"),  ("11129756", "Fastenal"),
    ("11129757", "Fastenal"),
    ("0145966", "Fastenal"),   ("0145967", "Fastenal"),
    ("0145968", "Fastenal"),   ("0145969", "Fastenal"),
    ("0145970", "Fastenal"),
]

# 19. IKO (needle bearings, linear guides) — 15 parts
iko = [
    ("LWLF14-B", "IKO"),   ("LWLF18-B", "IKO"),   ("LWLF24-B", "IKO"),
    ("LWLF30-B", "IKO"),   ("LWLF42-B", "IKO"),
    ("CRB4010", "IKO"),    ("CRB5013", "IKO"),     ("CRB6013", "IKO"),
    ("CRB8016", "IKO"),    ("CRB10020", "IKO"),
    ("NAF122413", "IKO"),  ("NAF152413", "IKO"),
    ("NAF203516", "IKO"),  ("NAF254517", "IKO"),
    ("TAF-081412", "IKO"),
]

# 20. Pall (filtration) — 15 parts
pall = [
    ("AB1DFL7PH4", "Pall"), ("AB1DFL7PH6", "Pall"),
    ("AB1DFL7PP4", "Pall"), ("AB1DFL7PP6", "Pall"),
    ("PLF010", "Pall"),     ("PLF020", "Pall"),
    ("PLF050", "Pall"),     ("PLF100", "Pall"),
    ("HC9600FKN8H", "Pall"), ("HC9600FKN13H", "Pall"),
    ("HC9600FKN16H", "Pall"),
    ("DFU010B", "Pall"),    ("DFU020B", "Pall"),
    ("DFU050B", "Pall"),    ("DFU100B", "Pall"),
]

# 21. MKS Instruments (pressure, flow, power) — 15 parts
mks = [
    ("722B13TCD2FA", "MKS Instruments"),
    ("722B13TCD2FB", "MKS Instruments"),
    ("627D01TDC1B", "MKS Instruments"),
    ("627D11TDC1B", "MKS Instruments"),
    ("1179C00812CR14V", "MKS Instruments"),
    ("1179C00832CR14V", "MKS Instruments"),
    ("1479A00824CR14V", "MKS Instruments"),
    ("GE50A013203RCJ010", "MKS Instruments"),
    ("GE50A013503RCJ010", "MKS Instruments"),
    ("PDR900-1", "MKS Instruments"),
    ("PDR900-2", "MKS Instruments"),
    ("925-11001-2", "MKS Instruments"),
    ("925-11003-2", "MKS Instruments"),
    ("274005-KF25", "MKS Instruments"),
    ("274010-KF25", "MKS Instruments"),
]

# 22. Specialty Bolt (fasteners) — 15 parts
specialty_bolt = [
    ("25N150FEWS", "Specialty Bolt & Screw"),
    ("25N200FEWS", "Specialty Bolt & Screw"),
    ("38N150FEWS", "Specialty Bolt & Screw"),
    ("38N200FEWS", "Specialty Bolt & Screw"),
    ("50N175FEWS", "Specialty Bolt & Screw"),
    ("50N200FEWS", "Specialty Bolt & Screw"),
    ("10N050FEWS", "Specialty Bolt & Screw"),
    ("10N075FEWS", "Specialty Bolt & Screw"),
    ("25A100FWS", "Specialty Bolt & Screw"),
    ("25A125FWS", "Specialty Bolt & Screw"),
    ("25A150FWS", "Specialty Bolt & Screw"),
    ("38A100FWS", "Specialty Bolt & Screw"),
    ("38A125FWS", "Specialty Bolt & Screw"),
    ("50A100FWS", "Specialty Bolt & Screw"),
    ("50A125FWS", "Specialty Bolt & Screw"),
]

# Combine all
all_mfgs = [
    mcmaster, smc, thk, nsk, swagelok, parker, keyence, omron,
    festo, hiwin, te, ntn, misumi, ckd, edwards, vat, entegris,
    fastenal, iko, pall, mks, specialty_bolt,
]

for mfg_list in all_mfgs:
    PARTS.extend(mfg_list)

print(f"Total parts: {len(PARTS)}")
print(f"Manufacturers: {len(set(p[1] for p in PARTS))}")

# Write Excel
output_path = Path(__file__).parent / "input" / "PartClassifierInput_400.xlsx"
wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Parts"

# Headers matching expected format
headers = ["Part Number", "Part Name", "Manufacturer Part Number", "Manufacturer Name", "Unit of Measure"]
ws.append(headers)

for i, (mfg_pn, mfg_name) in enumerate(PARTS, 1):
    ws.append([
        f"TEST-{i:04d}",     # Part Number (internal)
        "",                    # Part Name (blank per user request)
        mfg_pn,               # Manufacturer Part Number
        mfg_name,             # Manufacturer Name
        "mm",                 # Unit of Measure
    ])

wb.save(output_path)
print(f"Saved: {output_path}")
print(f"\nManufacturer breakdown:")
from collections import Counter
counts = Counter(p[1] for p in PARTS)
for mfg, count in counts.most_common():
    print(f"  {mfg}: {count}")
