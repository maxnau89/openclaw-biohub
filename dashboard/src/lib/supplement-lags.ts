// Evidence-based default lag hours and typical daily doses per supplement.
// Keys are lowercase normalized names for fuzzy matching.

export const SUPPLEMENT_LAGS: Record<string, { lag_hours: number; evidence: string }> = {
  // === Core minerals ===
  "magnesium":              { lag_hours: 2,   evidence: "acute effect on sleep/HRV" },
  "zinc":                   { lag_hours: 24,  evidence: "24h immune/hormonal effect" },
  "selen":                  { lag_hours: 72,  evidence: "3-day antioxidant/thyroid response" },
  "selenium":               { lag_hours: 72,  evidence: "3-day antioxidant/thyroid response" },
  "kupfer":                 { lag_hours: 48,  evidence: "2-day enzymatic cofactor response" },
  "copper":                 { lag_hours: 48,  evidence: "2-day enzymatic cofactor response" },

  // === Fat-soluble vitamins ===
  "vitamin d":              { lag_hours: 168, evidence: "7-day tissue saturation" },
  "vitamin a":              { lag_hours: 72,  evidence: "3-day liver accumulation" },
  "vitamin e":              { lag_hours: 48,  evidence: "2-day antioxidant membrane integration" },

  // === Water-soluble vitamins ===
  "vitamin c":              { lag_hours: 4,   evidence: "acute antioxidant/immune response" },
  "vitamin b":              { lag_hours: 6,   evidence: "same-day energy metabolism boost" },
  "pyridoxal":              { lag_hours: 4,   evidence: "P5P active B6, rapid neurological effect" },
  "p5p":                    { lag_hours: 4,   evidence: "P5P active B6, rapid neurological effect" },
  "pantothensäure":         { lag_hours: 6,   evidence: "pantothenic acid, adrenal/energy" },
  "pantothenic":            { lag_hours: 6,   evidence: "pantothenic acid, adrenal/energy" },
  "biotin":                 { lag_hours: 24,  evidence: "daily turnover, hair/nail effects weeks" },

  // === Omega fatty acids ===
  "omega-3":                { lag_hours: 72,  evidence: "3-day inflammation response" },
  "omega 3":                { lag_hours: 72,  evidence: "3-day inflammation response" },
  "dha":                    { lag_hours: 72,  evidence: "brain lipid incorporation 3-7 days" },
  "epa":                    { lag_hours: 48,  evidence: "2-day anti-inflammatory eicosanoid shift" },
  "fischöl":                { lag_hours: 72,  evidence: "3-day inflammation response" },
  "fish oil":               { lag_hours: 72,  evidence: "3-day inflammation response" },

  // === Performance / Energy ===
  "creatine":               { lag_hours: 0,   evidence: "same-day performance" },
  "kreatin":                { lag_hours: 0,   evidence: "same-day performance" },
  "taurin":                 { lag_hours: 1,   evidence: "acute osmoregulation/HRV effect" },
  "taurine":                { lag_hours: 1,   evidence: "acute osmoregulation/HRV effect" },
  "l-citrullin":            { lag_hours: 1,   evidence: "acute NO/blood-flow boost" },
  "citrulline":             { lag_hours: 1,   evidence: "acute NO/blood-flow boost" },
  "alcar":                  { lag_hours: 2,   evidence: "acute mitochondrial/cognitive effect" },
  "acetyl-l-carnitin":      { lag_hours: 2,   evidence: "acute mitochondrial/cognitive effect" },
  "coq10":                  { lag_hours: 72,  evidence: "mitochondrial response" },
  "ubiquinol":              { lag_hours: 72,  evidence: "mitochondrial response" },
  "ubiquinon":              { lag_hours: 72,  evidence: "mitochondrial response" },
  "nmn":                    { lag_hours: 24,  evidence: "NAD+ precursor, 24h cellular energy" },
  "beta-ecdysteron":        { lag_hours: 24,  evidence: "anabolic signaling, 24-48h onset" },
  "ecdysteron":             { lag_hours: 24,  evidence: "anabolic signaling, 24-48h onset" },
  "maca":                   { lag_hours: 336, evidence: "2-week hormonal/energy adaptation" },
  "fadogia":                { lag_hours: 168, evidence: "7-day testosterone-axis response" },
  "mucuna":                 { lag_hours: 2,   evidence: "L-DOPA precursor, acute dopamine effect" },

  // === Adaptogens / Stress ===
  "ashwagandha":            { lag_hours: 336, evidence: "2-week HPA-axis adaptation (KSM-66)" },
  "withania":               { lag_hours: 336, evidence: "2-week HPA-axis adaptation" },
  "rhodiola":               { lag_hours: 48,  evidence: "2-day adaptogen/cortisol effect" },
  "l-theanin":              { lag_hours: 1,   evidence: "acute anxiolytic/alpha-wave effect" },
  "theanine":               { lag_hours: 1,   evidence: "acute anxiolytic/alpha-wave effect" },
  "melatonin":              { lag_hours: 1,   evidence: "acute sleep onset" },
  "baldrian":               { lag_hours: 2,   evidence: "acute GABA-ergic sedation" },
  "valerian":               { lag_hours: 2,   evidence: "acute GABA-ergic sedation" },
  "5-htp":                  { lag_hours: 2,   evidence: "acute serotonin precursor" },

  // === Nootropics / Cognitive ===
  "l-tyrosin":              { lag_hours: 1,   evidence: "acute catecholamine precursor" },
  "tyrosine":               { lag_hours: 1,   evidence: "acute catecholamine precursor" },
  "uridinmonophosphat":     { lag_hours: 24,  evidence: "synaptic membrane building, days-weeks" },
  "uridine":                { lag_hours: 24,  evidence: "synaptic membrane building, days-weeks" },
  "methylenblau":           { lag_hours: 1,   evidence: "acute mitochondrial electron transport" },
  "methylene blue":         { lag_hours: 1,   evidence: "acute mitochondrial electron transport" },
  "l-histidin":             { lag_hours: 4,   evidence: "histamine/carnosine precursor" },
  "histidine":              { lag_hours: 4,   evidence: "histamine/carnosine precursor" },

  // === Hormonal support ===
  "dim":                    { lag_hours: 168, evidence: "7-day estrogen metabolism shift" },
  "sägepalme":              { lag_hours: 336, evidence: "2-week DHT/5AR inhibition" },
  "saw palmetto":           { lag_hours: 336, evidence: "2-week DHT/5AR inhibition" },
  "pygeum":                 { lag_hours: 336, evidence: "2-week prostate/DHT response" },
  "mönchspfeffer":          { lag_hours: 168, evidence: "7-day prolactin modulation" },
  "vitex":                  { lag_hours: 168, evidence: "7-day prolactin modulation" },

  // === Anti-inflammatory / Antioxidants ===
  "curcumin":               { lag_hours: 24,  evidence: "24h NF-kB/inflammatory pathway" },
  "kurkuma":                { lag_hours: 24,  evidence: "24h NF-kB/inflammatory pathway" },
  "turmeric":               { lag_hours: 24,  evidence: "24h NF-kB/inflammatory pathway" },
  "astaxanthin":            { lag_hours: 48,  evidence: "2-day carotenoid antioxidant uptake" },
  "resveratrol":            { lag_hours: 24,  evidence: "24h SIRT1/antioxidant response" },
  "luteolin":               { lag_hours: 24,  evidence: "24h mast-cell/neuroinflammation effect" },
  "sulforaphan":            { lag_hours: 12,  evidence: "12h Nrf2 antioxidant pathway activation" },
  "sulforaphane":           { lag_hours: 12,  evidence: "12h Nrf2 antioxidant pathway activation" },
  "broccoli":               { lag_hours: 12,  evidence: "12h Nrf2 via sulforaphane" },
  "bergamotte":             { lag_hours: 48,  evidence: "2-day lipid/cholesterol modulation" },
  "bergamot":               { lag_hours: 48,  evidence: "2-day lipid/cholesterol modulation" },
  "nac":                    { lag_hours: 4,   evidence: "acute glutathione precursor" },
  "n-acetylcystein":        { lag_hours: 4,   evidence: "acute glutathione precursor" },
  "pea":                    { lag_hours: 4,   evidence: "acute endocannabinoid anti-inflammatory" },
  "palmitoylethanolamid":   { lag_hours: 4,   evidence: "acute endocannabinoid anti-inflammatory" },

  // === Gut / Digestive ===
  "flohsamenschalen":       { lag_hours: 6,   evidence: "acute intestinal bulk/motility" },
  "psyllium":               { lag_hours: 6,   evidence: "acute intestinal bulk/motility" },
  "probiotika":             { lag_hours: 72,  evidence: "3-day microbiome shift onset" },
  "probiotic":              { lag_hours: 72,  evidence: "3-day microbiome shift onset" },
  "saccharomyces":          { lag_hours: 24,  evidence: "24h gut barrier restoration" },
  "laktase":                { lag_hours: 0,   evidence: "immediate lactose digestion" },
  "lactase":                { lag_hours: 0,   evidence: "immediate lactose digestion" },
  "enzyme":                 { lag_hours: 0,   evidence: "immediate digestive enzyme effect" },

  // === Protein / Structural ===
  "kollagen":               { lag_hours: 336, evidence: "2-week collagen synthesis response" },
  "collagen":               { lag_hours: 336, evidence: "2-week collagen synthesis response" },
  "lecithin":               { lag_hours: 48,  evidence: "2-day phospholipid/liver effect" },
  "lactoferrin":            { lag_hours: 24,  evidence: "24h antimicrobial/immune modulation" },
  "l-lysin":                { lag_hours: 24,  evidence: "24h collagen/carnitine synthesis" },
  "lysine":                 { lag_hours: 24,  evidence: "24h collagen/carnitine synthesis" },
  "whey":                   { lag_hours: 0,   evidence: "immediate muscle protein synthesis" },
  "protein":                { lag_hours: 0,   evidence: "immediate muscle protein synthesis" },

  // === Miscellaneous ===
  "berberin":               { lag_hours: 48,  evidence: "2-day AMPK/glucose metabolism effect" },
  "berberine":              { lag_hours: 48,  evidence: "2-day AMPK/glucose metabolism effect" },
  "matcha":                 { lag_hours: 1,   evidence: "acute caffeine+L-theanine focus effect" },
  "cbd":                    { lag_hours: 1,   evidence: "acute endocannabinoid modulation" },
};

// Typical number of units (capsules/tablets/scoops) taken per day.
export const SUPPLEMENT_DAILY_DOSE: Record<string, { units_per_day: number; note: string }> = {
  "magnesium":        { units_per_day: 1,  note: "1 capsule/day standard" },
  "zinc":             { units_per_day: 1,  note: "1 capsule/day" },
  "selen":            { units_per_day: 1,  note: "1 capsule/day" },
  "selenium":         { units_per_day: 1,  note: "1 capsule/day" },
  "kupfer":           { units_per_day: 1,  note: "1 capsule/day" },
  "vitamin d":        { units_per_day: 1,  note: "1 softgel/day" },
  "vitamin a":        { units_per_day: 1,  note: "1 capsule/day" },
  "vitamin e":        { units_per_day: 1,  note: "1 capsule/day" },
  "vitamin c":        { units_per_day: 2,  note: "2 caps/day (morning + evening)" },
  "vitamin b":        { units_per_day: 1,  note: "1 capsule/day" },
  "pyridoxal":        { units_per_day: 1,  note: "1 capsule/day" },
  "biotin":           { units_per_day: 1,  note: "1 capsule/day" },
  "omega-3":          { units_per_day: 3,  note: "3 softgels/day EPA+DHA protocol" },
  "omega 3":          { units_per_day: 3,  note: "3 softgels/day" },
  "fischöl":          { units_per_day: 3,  note: "3 softgels/day" },
  "fish oil":         { units_per_day: 3,  note: "3 softgels/day" },
  "creatine":         { units_per_day: 1,  note: "1 scoop (5g)/day" },
  "kreatin":          { units_per_day: 1,  note: "1 scoop (5g)/day" },
  "taurin":           { units_per_day: 1,  note: "1 capsule or scoop/day" },
  "coq10":            { units_per_day: 1,  note: "1 capsule/day with fat" },
  "ubiquinol":        { units_per_day: 1,  note: "1 capsule/day" },
  "nmn":              { units_per_day: 1,  note: "1 capsule/day" },
  "ashwagandha":      { units_per_day: 2,  note: "2 caps/day KSM-66 standard (300mg each)" },
  "rhodiola":         { units_per_day: 1,  note: "1 capsule/day" },
  "l-theanin":        { units_per_day: 1,  note: "1–2 caps/day" },
  "theanine":         { units_per_day: 1,  note: "1–2 caps/day" },
  "melatonin":        { units_per_day: 1,  note: "1 tablet before sleep" },
  "baldrian":         { units_per_day: 2,  note: "2 caps before bed" },
  "5-htp":            { units_per_day: 1,  note: "1 capsule/day" },
  "l-tyrosin":        { units_per_day: 1,  note: "1–2 caps/day" },
  "curcumin":         { units_per_day: 2,  note: "2 caps/day with fat" },
  "astaxanthin":      { units_per_day: 1,  note: "1 softgel/day" },
  "resveratrol":      { units_per_day: 1,  note: "1 capsule/day" },
  "berberin":         { units_per_day: 3,  note: "3x 500mg/day with meals" },
  "berberine":        { units_per_day: 3,  note: "3x 500mg/day with meals" },
  "nac":              { units_per_day: 2,  note: "2 caps/day (morning + evening)" },
  "kollagen":         { units_per_day: 1,  note: "1 scoop/day" },
  "collagen":         { units_per_day: 1,  note: "1 scoop/day" },
  "whey":             { units_per_day: 1,  note: "1 scoop/day" },
  "probiotika":       { units_per_day: 1,  note: "1 capsule/day" },
  "probiotic":        { units_per_day: 1,  note: "1 capsule/day" },
  "flohsamenschalen": { units_per_day: 3,  note: "3 portions/day (1 tbsp each)" },
  "dim":              { units_per_day: 1,  note: "1 capsule/day" },
  "sulforaphan":      { units_per_day: 1,  note: "1 capsule/day" },
  "broccoli":         { units_per_day: 1,  note: "1 capsule/day" },
  "maca":             { units_per_day: 1,  note: "1 scoop or capsule/day" },
};

/** Fuzzy-match a supplement name to get its lag hours. Returns 24 if no match. */
export function getLagHours(name: string): number {
  const key = name.toLowerCase();
  for (const [k, v] of Object.entries(SUPPLEMENT_LAGS)) {
    if (key.includes(k) || k.includes(key.split(' ')[0])) return v.lag_hours;
  }
  return 24;
}

/** Fuzzy-match a supplement name to get typical units per day. Returns 1 if no match. */
export function getDailyUnits(name: string): number {
  const key = name.toLowerCase();
  for (const [k, v] of Object.entries(SUPPLEMENT_DAILY_DOSE)) {
    if (key.includes(k) || k.includes(key.split(' ')[0])) return v.units_per_day;
  }
  return 1;
}
