#!/usr/bin/env python3
"""
parse_blood_panel.py - PDF blood panel parser for Mission Control (MVZ Duesseldorf format)

The MVZ lab format delivers all text as a single blob (no newlines).
Pattern: MarkerName [space?][+/-?]Value+Unit  RefLow-RefHigh [altersbezogen] [PrevValue Date]

Usage:
  python3 parse_blood_panel.py /path/to/file.pdf
  python3 parse_blood_panel.py --stdin    (reads text from stdin)

Outputs JSON array of marker objects.
"""

import sys, re, json

# ---------------------------------------------------------------------------
# Unit patterns (order: longest first to avoid partial matches)
# ---------------------------------------------------------------------------
UNITS = [
    'pg/Ery', '/µl', '/pl', '/nl', 'g/dl', 'ng/ml', 'ng/l', 'mg/dl',
    'mU/l', 'nmol/l', 'µg/l', 'IU/ml', 'µmol/l', 'mmol/l', 'U/l',
    'µg/dl', 'pmol/l', 'ng/dl', 'kU/l', 'pg/ml', 'fl', 'pg', '%',
]
UNIT_RE = '|'.join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))

# Ref range pattern: "11.3 - 43.2" or "< 5.0" or "0.27-4.2"
REF_RE = r'(?:[<≤>≥]\s*[0-9]+(?:[.,][0-9]+)?|[0-9]+(?:[.,][0-9]+)?\s*[-–]\s*[0-9]+(?:[.,][0-9]+)?)'

# Canonical unit map: lowercase → original case
UNIT_CANONICAL = {u.lower(): u for u in UNITS}

# ---------------------------------------------------------------------------
# German → English marker name mapping
# ---------------------------------------------------------------------------
# Keys are the exact German names as they appear in MVZ lab reports (lowercase for matching)
MARKERS = {
    # Hämatologie
    'leukozyten':                       ('WBC',              '/µl'),
    'neutrophile granulozyten':         ('Neutrophils',      '%'),
    'lymphozyten':                      ('Lymphocytes',      '%'),
    'monozyten':                        ('Monocytes',        '%'),
    'eosinophile':                      ('Eosinophils',      '%'),
    'basophile':                        ('Basophils',        '%'),
    'hämoglobin':                       ('Hemoglobin',       'g/dl'),
    'hämatokrit':                       ('Hematocrit',       '%'),
    'erythrozyten':                     ('RBC',              '/pl'),
    'mcv':                              ('MCV',              'fl'),
    'mch':                              ('MCH',              'pg/Ery'),
    'mchc':                             ('MCHC',             'g/dl'),
    'thrombozyten':                     ('Platelets',        '/nl'),
    # Klinische Chemie
    'ferritin':                         ('Ferritin',         'ng/ml'),
    'albumin':                          ('Albumin',          'mg/dl'),
    'tsh basal':                        ('TSH',              'mU/l'),
    'tsh':                              ('TSH',              'mU/l'),
    'alt (gpt)':                        ('ALT (GPT)',        'U/l'),
    'alanin-aminotransferase':          ('ALT (GPT)',        'U/l'),
    'gpt':                              ('ALT (GPT)',        'U/l'),
    'ast (got)':                        ('AST (GOT)',        'U/l'),
    'aspartat-aminotransferase':        ('AST (GOT)',        'U/l'),
    'got':                              ('AST (GOT)',        'U/l'),
    'ggt':                              ('GGT',              'U/l'),
    'gamma-gt':                         ('GGT',              'U/l'),
    'ap':                               ('Alkaline Phosphatase', 'U/l'),
    'alkalische phosphatase':           ('Alkaline Phosphatase', 'U/l'),
    'bilirubin, gesamt':                ('Bilirubin',        'mg/dl'),
    'bilirubin':                        ('Bilirubin',        'mg/dl'),
    'gesamtbilirubin':                  ('Bilirubin',        'mg/dl'),
    'kreatinin':                        ('Creatinine',       'mg/dl'),
    'harnstoff':                        ('BUN',              'mg/dl'),
    'glukose':                          ('Glucose',          'mg/dl'),
    'hba1c':                            ('HbA1c (DCCT)',     '%'),
    'cholesterin':                      ('Cholesterol',      'mg/dl'),
    'hdl-cholesterin':                  ('HDL',              'mg/dl'),
    'ldl-cholesterin':                  ('LDL',              'mg/dl'),
    'triglyzeride':                     ('Triglycerides',    'mg/dl'),
    'triglyceride':                     ('Triglycerides',    'mg/dl'),
    'c-reaktives protein':              ('CRP (hs)',         'mg/l'),
    'crp':                              ('CRP (hs)',         'mg/l'),
    'harnsäure':                        ('Uric Acid',        'mg/dl'),
    'kalium':                           ('Potassium',        'mmol/l'),
    'natrium':                          ('Sodium',           'mmol/l'),
    'calcium':                          ('Calcium',          'mmol/l'),
    'magnesium':                        ('Magnesium',        'mmol/l'),
    'eisen':                            ('Iron',             'µg/dl'),
    'transferrin':                      ('Transferrin',      'mg/dl'),
    'vitamin b12':                      ('Vitamin B12',      'pg/ml'),
    '25-oh-vitamin d':                  ('Vitamin D (25-OH)', 'ng/ml'),
    'vitamin d':                        ('Vitamin D (25-OH)', 'ng/ml'),
    # Hormone
    'östradiol':                        ('Estradiol',        'pg/ml'),
    'estradiol':                        ('Estradiol',        'pg/ml'),
    'testosteron':                      ('Testosterone',     'ng/ml'),
    'freies testosteron':               ('Free Testosterone', 'ng/l'),
    'shbg=sexualhormon-bindendes-globulin': ('SHBG',         'nmol/l'),
    'shbg':                             ('SHBG',             'nmol/l'),
    'freier-androgenindex (testost./shbg)': ('Free Androgen Index', None),
    'lh':                               ('LH',               'IU/l'),
    'fsh':                              ('FSH',              'IU/l'),
    'prolaktin':                        ('Prolactin',        'ng/ml'),
    'cortisol':                         ('Cortisol',         'µg/dl'),
    'dhea-s':                           ('DHEA-S',           'µg/dl'),
    'igf-1':                            ('IGF-1',            'ng/ml'),
    'psa':                              ('PSA',              'ng/ml'),
    'psa gesamt':                       ('PSA',              'ng/ml'),
    # Thyroid extras
    'freies t3':                        ('Free T3',          'pg/ml'),
    'freies t4':                        ('Free T4',          'ng/dl'),
    'ft3':                              ('Free T3',          'pg/ml'),
    'ft4':                              ('Free T4',          'ng/dl'),
}

def parse_number(s: str):
    if not s:
        return None
    try:
        return float(s.strip().replace(',', '.'))
    except ValueError:
        return None

def parse_ref(ref_str: str):
    ref_str = ref_str.strip()
    m = re.match(r'^([0-9.,]+)\s*[-–]\s*([0-9.,]+)$', ref_str)
    if m:
        return parse_number(m.group(1)), parse_number(m.group(2))
    m = re.match(r'^[<≤]\s*([0-9.,]+)$', ref_str)
    if m:
        return None, parse_number(m.group(1))
    m = re.match(r'^[>≥]\s*([0-9.,]+)$', ref_str)
    if m:
        return parse_number(m.group(1)), None
    return None, None

def infer_status(value, ref_low, ref_high, flag=''):
    flag = (flag or '').strip()
    if flag == '+' or flag == 'H':
        return 'high'
    if flag == '-' or flag == 'L':
        return 'low'
    if value is None:
        return 'unknown'
    if ref_high is not None and value > ref_high:
        return 'high'
    if ref_low is not None and value < ref_low:
        return 'low'
    if ref_low is not None or ref_high is not None:
        return 'normal'
    return 'unknown'

def search_marker(text_lower: str, german_name: str, english_name: str, used_spans: list):
    """
    Search for a German marker name in the text blob and extract its value.
    - used_spans: list of (start, end) already matched; skip overlapping matches
      (prevents 'testosteron' from matching inside 'freies testosteron')
    Returns (result_dict | None), mutates used_spans in-place.
    """
    name_pat = re.escape(german_name)
    pattern = re.compile(
        name_pat +
        # optional suffix between name and value — covers:
        #   "=ASAT/AST (IFCC)"  →  GOT=ASAT/AST (IFCC) 28U/l
        #   "(berechnet)"       →  freies Testosteron (berechnet) 41.6ng/l
        #   "(DCCT-Standard.)"  →  HbA1c (DCCT-Standardisierung) 5.1%
        r'(?:=[^\s(]+)?(?:\s*\([^)]*\))?\s*([+\-]?)([0-9]+(?:[.,][0-9]+)?)(' + UNIT_RE + r')\s+(' + REF_RE + r')',
        re.IGNORECASE | re.UNICODE
    )

    for m in pattern.finditer(text_lower):
        start = m.start()
        # Skip if this match falls inside an already-used span
        if any(s <= start < e for s, e in used_spans):
            continue

        used_spans.append((m.start(), m.end()))

        flag      = m.group(1)
        value     = parse_number(m.group(2))
        unit_raw  = m.group(3)
        unit      = UNIT_CANONICAL.get(unit_raw.lower(), unit_raw)  # restore original case
        ref       = m.group(4)
        ref_low, ref_high = parse_ref(ref)
        status    = infer_status(value, ref_low, ref_high, flag)

        return {
            'marker_name': english_name,
            'value':       value,
            'unit':        unit,
            'ref_low':     ref_low,
            'ref_high':    ref_high,
            'status':      status,
        }

    return None


def parse_text(text: str) -> list:
    text_lower = text.lower()
    markers = []
    seen_english = set()
    used_spans: list = []  # track matched positions to avoid substring collisions

    # Longer names first → "freies testosteron" before "testosteron"
    sorted_markers = sorted(MARKERS.items(), key=lambda x: len(x[0]), reverse=True)

    for german, (english, _default_unit) in sorted_markers:
        if english.lower() in seen_english:
            continue
        result = search_marker(text_lower, german, english, used_spans)
        if result:
            seen_english.add(english.lower())
            markers.append(result)

    markers.sort(key=lambda m: m['marker_name'])
    return markers

def extract_text_from_pdf(path: str) -> str:
    from pdfminer.high_level import extract_text as _extract
    return _extract(path)

def main():
    if len(sys.argv) < 2:
        print(json.dumps({'error': 'Usage: parse_blood_panel.py <file.pdf> or --stdin'}), file=sys.stderr)
        sys.exit(1)

    if sys.argv[1] == '--stdin':
        text = sys.stdin.read()
    else:
        try:
            text = extract_text_from_pdf(sys.argv[1])
        except Exception as e:
            print(json.dumps({'error': f'PDF extraction failed: {e}'}), file=sys.stderr)
            sys.exit(1)

    markers = parse_text(text)
    print(json.dumps(markers, ensure_ascii=False))

if __name__ == '__main__':
    main()
