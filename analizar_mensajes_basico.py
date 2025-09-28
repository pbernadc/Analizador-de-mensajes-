"""
Analizador de mensajes básico (v1 mejorado)
---------------------------------
Pipeline básico para analizar mensajes (versión 1)

Qué hace:
1) Lee el Excel del corpus.
2) Busca y diferencia la columna de texto.
3) Calcula rasgos:
   - Claridad (legibilidad Szigriszt-Pazos*)
   - Concisión (longitud del mensaje)
   - Alarmismo (mayúsculas, !!! y palabras "alarmistas")
   - Emotividad (emojis + exclamaciones)
4) Devuelve puntuaciones [0,5] para cada rasgo.
5) Guarda un Excel y un CSV con los resultados en columnas nuevas.

Es necesario instalar las siguientes librerías:
    pip install pandas openpyxl textstat emoji spacy

Uso en el terminal:
    python analizar_mensajes_basico.py --input "Corpus alertas y mensajes.xlsx" --sheet "Sheet1"

    * Szigriszt-Pazos: https://legible.es/blog/perspicuidad-szigriszt-pazos/ 
"""

import argparse
import math
import re
from pathlib import Path

import pandas as pd
import textstat
import emoji
import spacy

# ------------------------------
# Utilidades

try:
    NLP = spacy.load("es_core_news_md")
except Exception as e:
    raise RuntimeError(
        "No se encuentra el modelo de spaCy 'es_core_news_md'. "
        "Puedes instalarlo con: python -m spacy download es_core_news_md"
    ) from e

# ------------------------------

ALARM_WORDS = {
    "URGENTE", "ATENCIÓN", "ALERTA", "PÁNICO", "CAOS",
    "APOCALÍPTICO", "DEVASTADOR", "DESASTRE", "TERRIBLE", "CATASTRÓFICO",
    "GRAVE", "PELIGRO", "PELIGROSO", "RIESGO", "INCENDIO", "INUNDACIÓN",
    "ABANDONE", "EVITE", "PROHIBIDO", "CERRADO", "EMERGENCIA",
    "GRAVE PELIGRO", "RIESGO EXTREMO", "NO SALGA DE CASA"
}

POSSIBLE_TEXT_COLS = [
    "texto", "mensaje", "text", "msg", "contenido", "body", "post"
]

DIRECTIVE_LEX = {
    "evacuar","evitar","abandonar","dirigirse","llamar","no","cruzar","conducir",
    "alejarse","permanecer","seguir","esperar","mantenerse","refugiarse","acudir",
    "prohibir","cerrar","suspender","confinar","desalojar"
}

VALORATIVOS = {
    "terrible","brutal","apocalíptico","devastador","horrible","trágico","atroz",
    "increíble","tremendo","descomunal","catastrófico","espantoso"
}

URGENT_TERMS = {
    "inmediatamente","de inmediato","ahora","ya","urgente","a la mayor brevedad",
    "hasta nuevo aviso","de forma inmediata","en este momento"
}

INTERJECCIONES = {
    "ay","uff","uf","madre mía","madremia","dios","por favor","porfa","ojalá","eh"
}

METAPHORS = {
    "mar de fuego","río de agua","el cielo se cae","la ciudad arde","marea de lodo",
    "lluvia de piedras","tormenta que muerde","pared de agua","infierno de fuego"
}

#Este método intenta detectar automáticamente la columna de texto en el DataFrame
def autodetect_text_column(df: pd.DataFrame) -> str:
    # 1) intenta por nombres comunes
    for c in df.columns:
        if str(c).strip().lower() in POSSIBLE_TEXT_COLS:
            return c
    # 2) si no, elige la columna de tipo object con mayor longitud media
    candidates = []
    for c in df.columns:
        if pd.api.types.is_object_dtype(df[c]):
            series = df[c].dropna().astype(str)
            if len(series) == 0:
                continue
            avg_len = series.str.len().mean()
            candidates.append((c, avg_len))
    if not candidates:
        raise ValueError("No encuentro una columna de texto. Asegúrate de tener una columna tipo string.")
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]

#Este método calcula el porcentaje de letras mayúsculas en el texto
def pct_upper(text: str) -> float:
    letters = [ch for ch in text if ch.isalpha() and ch.isascii()]
    if not letters:
        return 0.0
    return sum(ch.isupper() for ch in letters) / len(letters)

#Este método cuenta las exclamaciones en el texto
def count_exclamations(text: str) -> int:
    return text.count("!") + text.count("¡")

#Este método cuenta los emojis en el texto
def count_emojis(text: str) -> int:
    # emoji.emoji_list(text) devuelve una lista de dicts con coincidencias
    return len(emoji.emoji_list(text))

#Este método reescala un valor linealmente entre 0 y 1, recortando los extremos de las puntuaciones que se le dan a cada rasgo
def rescale(value: float, lo: float, hi: float) -> float:
    """Mapea linealmente value desde [lo, hi] a [0, 1] y recorta extremos."""
    if math.isinf(value) or math.isnan(value):
        return 0.0
    if hi == lo:
        return 0.0
    x = (value - lo) / (hi - lo)
    return max(0.0, min(1.0, x))

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

# ------------------------------
# Estos métodos extraen diferentes rasgos y puntuaciones de un texto
# ------------------------------


def features_from_text(text: str) -> dict:
    # Normaliza a str garantiza que siempre sea string
    if not isinstance(text, str):
        text = "" if pd.isna(text) else str(text)

    text_norm = text.strip()
    length_chars = len(text_norm)
    tokens = re.findall(r"\w+", text_norm, flags=re.UNICODE)
    length_tokens = len(tokens)

    # spaCy que procesa el texto
    doc = NLP(text_norm)

    # Legibilidad Szigriszt-Pazos
    try:
        szigriszt = textstat.szigriszt_pazos(text_norm)
    except Exception:
        szigriszt = float("nan")

    # Emojis / exclamaciones / mayúsculas
    exclam = count_exclamations(text_norm)
    emojis_count = count_emojis(text_norm)
    upper_ratio = pct_upper(text_norm)

    # Alarm words consigue que no se omitan las que van con un .,;:!?¡¿
    words_up = set(w.upper().strip(".,;:!?¡¿") for w in tokens)
    alarm_hits = sum(1 for w in words_up if w in ALARM_WORDS)
    text_upper = text_norm.upper()
    for phrase in ALARM_WORDS:
        if " " in phrase and phrase in text_upper:
            alarm_hits += 1

    # === Directividad ===

    # Imperativo morfológico
    imp_verbs = sum(1 for t in doc if t.pos_ == "VERB" and "Imp" in t.morph.get("Mood"))
    # Léxico directivo (lemmas)
    dir_lex = sum(1 for t in doc if t.lemma_.lower() in DIRECTIVE_LEX)
    # Urgencia léxica quiere decir, palabras que indican urgencia
    low = text_norm.lower()
    urgency_hits = 0
    for u in URGENT_TERMS:
        if u in low:
            urgency_hits += 1

    # === Especificidad (ubicación, zona, hora) ===
    ner_loc = sum(1 for ent in doc.ents if ent.label_ in ("LOC","GPE"))
    ner_date = sum(1 for ent in doc.ents if ent.label_ == "DATE")
    ner_time = sum(1 for ent in doc.ents if ent.label_ == "TIME")
    num_count = sum(1 for t in doc if t.like_num)
    # patrones sencillos (horas 18:30)
    if re.search(r"\b\d{1,2}[:.]\d{2}\b", text_norm):
        ner_time += 1

    # === Autoridad ===
    AUTORIDADES = {
        "112","protección civil","aemet","dgt","ume","unidad militar de emergencias",
        "guardia civil","ayuntamiento","delegación del gobierno","gobierno",
        "red de alerta nacional","policía","bomberos"
    }
    autoridad_hits = 0
    autoridad_fuentes = ""
    for a in AUTORIDADES:
        if a in low:
            autoridad_hits += 1
            if not autoridad_fuentes:
                autoridad_fuentes = a
    # también cuenta ORG por NER
    autoridad_hits += sum(1 for ent in doc.ents if ent.label_ == "ORG")

    # === Tono neutral (insumos) ===
    valorativos_hits = sum(1 for t in doc if t.pos_ == "ADJ" and t.lemma_.lower() in VALORATIVOS)

    # === Emotividad (extensión: interjecciones) ===
    interj_hits = 0
    for interj in INTERJECCIONES:
        if re.search(rf"\b{re.escape(interj)}\b", low):
            interj_hits += 1

    # === Metáforas (básico) ===
    metafora_hits = 0
    for m in METAPHORS:
        if m in low:
            metafora_hits += 1
    # patrón "X de Y" (muy general → solo si aparece junto a términos de desastre)
    if re.search(r"\b(\w+)\s+de\s+(fuego|agua|barro|caos|desastre)\b", low):
        metafora_hits += 1

    # === Tiempo verbal dominante ===
    tense_counts = {"Pres":0,"Past":0,"Fut":0}
    for t in doc:
        if t.pos_ == "VERB" and "Fin" in t.morph.get("VerbForm"):
            for k in ("Pres","Past","Fut"):
                if k in t.morph.get("Tense"):
                    tense_counts[k] += 1
    if sum(tense_counts.values()) == 0:
        tiempo_dom = "Desconocido"
    else:
        tiempo_dom = max(tense_counts, key=tense_counts.get)

    # === Auto-etiquetas (ideas clave / anomalías) ===
    tags = []
    if re.search(r"https?://|www\.", low): tags.append("URL")
    if re.search(r"\b\d{3}[-\s]?\d{3}[-\s]?\d{3,4}\b", low) or "112" in low: tags.append("Telefono")
    if "#" in text_norm: tags.append("Hashtag")
    if "@" in text_norm: tags.append("Mencion")
    if upper_ratio > 0.4: tags.append("MAYUSCULAS")
    if length_tokens < 8: tags.append("Muy_corto")
    if length_tokens > 120: tags.append("Muy_largo")
    auto_etiquetas = ", ".join(tags)

    return {
        # originales + nuevos rasgos
        "len_chars": length_chars,
        "len_tokens": length_tokens,
        "szigriszt": szigriszt,
        "exclam_count": exclam,
        "emoji_count": emojis_count,
        "upper_ratio": upper_ratio,
        "alarm_hits": alarm_hits,

        "direct_imp_count": imp_verbs,
        "direct_lex_hits": dir_lex,
        "urgency_hits": urgency_hits,

        "ner_loc": ner_loc,
        "ner_date": ner_date,
        "ner_time": ner_time,
        "num_count": num_count,

        "autoridad_hits": autoridad_hits,
        "autoridad_fuentes": autoridad_fuentes,

        "valorativos_hits": valorativos_hits,
        "interj_hits": interj_hits,

        "metafora_hits": metafora_hits,
        "TiempoDominante": tiempo_dom,
        "AutoEtiquetas": auto_etiquetas,
    }


def score_from_features(f: dict) -> dict:
    # Claridad
    claridad01 = rescale(f.get("szigriszt", 0.0), 30.0, 90.0)
    claridad = round(5 * claridad01, 2)

    # Concisión
    t = f.get("len_tokens", 0)
    if t <= 10:
        concision01 = 0.7
    elif 10 < t <= 40:
        concision01 = 1.0
    elif 40 < t <= 80:
        concision01 = rescale(-t, -80.0, -40.0)
    else:
        concision01 = 0.1
    concision = round(5 * clamp01(concision01), 2)

    # Alarmismo
    alarm_01 = (
        0.5 * rescale(f.get("exclam_count", 0), 0, 5) +
        0.3 * rescale(f.get("upper_ratio", 0), 0.0, 0.3) +
        0.2 * rescale(f.get("alarm_hits", 0), 0, 3)
    )
    alarmismo = round(5 * clamp01(alarm_01), 2)

    # Emotividad
    emo_01 = (
        0.7 * rescale(f.get("emoji_count", 0), 0, 3) +
        0.3 * rescale(f.get("exclam_count", 0), 0, 5)
    )
    emotividad = round(5 * clamp01(emo_01), 2)

def score_from_features(f: dict) -> dict:

    # Claridad
    claridad01 = rescale(f.get("szigriszt", 0.0), 30.0, 90.0)
    claridad = round(5 * claridad01, 2)
    # Concisión
    t = f.get("len_tokens", 0)
    if t <= 10:
        concision01 = 0.7
    elif 10 < t <= 40:
        concision01 = 1.0
    elif 40 < t <= 80:
        concision01 = rescale(-t, -80.0, -40.0)
    else:
        concision01 = 0.1
    concision = round(5 * clamp01(concision01), 2)
    # Alarmismo
    alarm_01 = (
        0.5 * rescale(f.get("exclam_count", 0), 0, 5) +
        0.3 * rescale(f.get("upper_ratio", 0), 0.0, 0.3) +
        0.2 * rescale(f.get("alarm_hits", 0), 0, 3)
    )
    alarmismo = round(5 * clamp01(alarm_01), 2)
    #Emotividad
    emo_01 = (
        0.6 * rescale(f.get("emoji_count", 0), 0, 3) +
        0.2 * rescale(f.get("exclam_count", 0), 0, 5) +
        0.2 * rescale(f.get("interj_hits", 0), 0, 2)
    )
    emotividad = round(5 * clamp01(emo_01), 2)

    
    # Directividad
    dir01 = 0.6 * rescale(f.get("direct_imp_count", 0), 0, 3) + \
            0.4 * rescale(f.get("direct_lex_hits", 0), 0, 3)
    directividad = round(5 * clamp01(dir01), 2)

    # Tono neutral (alto si baja emotividad/alarmismo y pocos valorativos)
    neutral01 = 1 - clamp01(0.5*alarm_01 + 0.3*emo_01 + 0.2*rescale(f.get("valorativos_hits",0), 0, 3))
    tono_neutral = round(5 * clamp01(neutral01), 2)

    # Especificidad (entidades y números)
    espec01 = (
        0.35 * rescale(f.get("ner_loc", 0), 0, 3) +
        0.25 * rescale(f.get("ner_date", 0), 0, 2) +
        0.25 * rescale(f.get("ner_time", 0), 0, 2) +
        0.15 * rescale(f.get("num_count", 0), 0, 5)
    )
    especificidad = round(5 * clamp01(espec01), 2)

    # Autoridad
    autoridad = round(5 * rescale(f.get("autoridad_hits", 0), 0, 3), 2)

    # Urgencia controlada: urgencia (urgency+imperativos) pero con calma (pocas exclam/mayús)
    urg_need = clamp01(rescale(f.get("urgency_hits", 0) + f.get("direct_imp_count", 0), 0, 4))
    calma = clamp01(1 - (0.5*rescale(f.get("exclam_count",0), 0, 5) + 0.5*rescale(f.get("upper_ratio",0), 0.0, 0.3)))
    urgencia_ctrl = round(5 * clamp01(0.6*urg_need + 0.4*calma), 2)

    # Metáforas (básico)
    metaforas = round(5 * rescale(f.get("metafora_hits", 0), 0, 2), 2)

    return {
        "Claridad_0a5": claridad,
        "Concision_0a5": concision,
        "Alarmismo_0a5": alarmismo,
        "Emotividad_0a5": emotividad,

        "Directividad_0a5": directividad,
        "TonoNeutral_0a5": tono_neutral,
        "Especificidad_0a5": especificidad,
        "Autoridad_0a5": autoridad,
        "UrgenciaControlada_0a5": urgencia_ctrl,
        "Metaforas_0a5": metaforas,

        # extras cualitativos
        "TiempoDominante": f.get("TiempoDominante","Desconocido"),
        "TipoRedaccion": (
            "Directiva/operativa" if directividad >= 3 and urgencia_ctrl >= 3 else
            "Exagerada/viral" if alarmismo >= 3 or emotividad >= 3 else
            "Narrativa/relato" if f.get("TiempoDominante") == "Past" else
            "Informativa"
        ),
        "AutoEtiquetas": f.get("AutoEtiquetas",""),
        "FuenteAutoridad": f.get("autoridad_fuentes",""),
    }


# ------------------------------
# Main
# ------------------------------

def main():
    parser = argparse.ArgumentParser(description="Analizador básico de mensajes (v1)")
    parser.add_argument("--input", required=True, help="Ruta al Excel de entrada (.xlsx)")
    parser.add_argument("--sheet", default=0, help="Índice o nombre de la hoja (por defecto 0)")
    args = parser.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        raise FileNotFoundError(f"No encuentro el fichero: {in_path}")

    print(f"✔ Leyendo Excel: {in_path} (sheet={args.sheet})")
    df = pd.read_excel(in_path, sheet_name=args.sheet)

    text_col = autodetect_text_column(df)
    print(f"✔ Columna de texto detectada: '{text_col}'")

    # Calcula rasgos y puntuaciones
    feat_rows = []
    score_rows = []
    for txt in df[text_col].astype(str).fillna(""):
        f = features_from_text(txt)
        s = score_from_features(f)
        feat_rows.append(f)
        score_rows.append(s)

    feats_df = pd.DataFrame(feat_rows)
    scores_df = pd.DataFrame(score_rows)

    out_df = pd.concat([df.reset_index(drop=True), feats_df, scores_df], axis=1)

    # Rutas de salida
    out_xlsx = in_path.with_name(in_path.stem + "_resultados_nuevo.xlsx")
    out_csv = in_path.with_name(in_path.stem + "_resultados_nuevo.csv")


    print(f"✔ Guardando resultados en:\n   - {out_xlsx}\n   - {out_csv}")
    out_df.to_excel(out_xlsx, index=False)
    out_df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # Resumen rápido en consola
    print("\nResumen rápido (medianas):")
    print(out_df[["Claridad_0a5","Concision_0a5","Alarmismo_0a5","Emotividad_0a5"]].median())

if __name__ == "__main__":
    main()
