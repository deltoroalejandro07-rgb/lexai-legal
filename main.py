import os
import re
import json
import pypdf
from flask import Flask, request, render_template
from openai import OpenAI

app = Flask(__name__)

# Configuración API Key OpenAI
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def anonimizar_texto_sensible(texto):
    if not texto:
        return texto
    texto = re.sub(r'\b[XYZxyz]?\d{7,8}[A-Za-z]\b', '[DNI/NIE ANONIMIZADO]', texto)
    texto = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL ANONIMIZADO]', texto)
    texto = re.sub(r'(\+34|0034)?\s*[6789]\d{2}\s*\d{3}\s*\d{3}', '[TELÉFONO ANONIMIZADO]', texto)
    return texto


def verificar_exactitud_datos(texto_original, resumen_generado):
    if not resumen_generado or not texto_original:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}
    
    cifras_encontradas = re.findall(r'\b\d+(?:[\.,]\d+)?\b', resumen_generado)
    if not cifras_encontradas:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}

    validadas = sum(1 for cifra in cifras_encontradas if cifra in texto_original)
    total = len(cifras_encontradas)
    score = round((validadas / total) * 100, 1) if total > 0 else 100

    return {
        "score_exactitud": score,
        "cifras_validadas": validadas,
        "total_cifras_verificadas": total
    }


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        return render_template('index.html')

    if 'file' not in request.files:
        return "No se ha subido ningún archivo.", 400

    file = request.files['file']
    if file.filename == '':
        return "No se ha seleccionado ningún archivo.", 400

    try:
        reader = pypdf.PdfReader(file)
        num_paginas = len(reader.pages)

        if num_paginas > 50:
            return "El documento supera el límite de 50 páginas.", 400

        texto_completo = ""
        for i, page in enumerate(reader.pages):
            contenido = page.extract_text()
            if contenido:
                texto_completo += f"\n--- PÁGINA {i+1} ---\n" + contenido

        if not texto_completo.strip():
            return "No se pudo extraer texto del PDF.", 400

        texto_completo = texto_completo[:90000]

    except Exception as e:
        return f"Error al procesar el archivo PDF: {str(e)}", 500

    categoria_seleccionada = request.form.get("categoria", "General / Otros")
    anonimizar = request.form.get("anonimizar_datos")

    if anonimizar:
        texto_completo = anonimizar_texto_sensible(texto_completo)

    num_preguntas_test = min(20, max(10, num_paginas * 2))

    prompt_sistema = f"""
Eres LexAI Enterprise 2.0. Analiza el documento PDF de la CATEGORÍA: "{categoria_seleccionada}".

1. SI ES "Educación / Académico":
   - "puntos_criticos_con_riesgo" debe ser [].
   - En "modulo_educacion": genera resumen_esquematico (5-8 puntos), glosario (8-10 términos) y {num_preguntas_test} preguntas_tipo_test.

2. OTRAS CATEGORÍAS:
   - Identifica partes y analiza riesgos/cláusulas en "puntos_criticos_con_riesgo".
   - Deja "modulo_educacion" vacío.

ESTRUCTURA JSON OBLIGATORIA:
{{
  "categoria_documento": "{categoria_seleccionada}",
  "tipo_documento": "Tipo exacto",
  "resumen_ejecutivo": "Resumen técnico",
  "puntos_criticos_con_riesgo": [],
  "modulo_educacion": {{
    "resumen_esquematico": [],
    "glosario": [],
    "preguntas_tipo_test": []
  }},
  "salida_accionable": "Recomendación final",
  "disclaimer": "Generado por IA."
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Texto del PDF:\n{texto_completo}"}
            ],
            temperature=0.2
        )

        json_raw = response.choices[0].message.content
        data = json.loads(json_raw)

        exactitud = verificar_exactitud_datos(texto_completo, data.get("resumen_ejecutivo", ""))
        data["verificacion_exactitud"] = exactitud

        return render_template('resultado.html', data=data)

    except Exception as e:
        return f"Error en el proceso de análisis de IA: {str(e)}", 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
