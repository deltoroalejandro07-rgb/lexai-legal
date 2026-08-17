import os
import re
import json
import pypdf
from flask import Flask, request, render_template
from openai import OpenAI

app = Flask(__name__)

# Configuración API Key OpenAI
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
client = OpenAI(
    api_key=OPENAI_API_KEY,
    timeout=60.0,
    max_retries=2
) if OPENAI_API_KEY else None


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

    if not client or not OPENAI_API_KEY:
        return "Error: No se ha detectado la clave API de OpenAI (OPENAI_API_KEY) en las variables de entorno.", 500

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

        texto_completo = texto_completo[:50000]

    except Exception as e:
        return f"Error al procesar el archivo PDF: {str(e)}", 500

    categoria_seleccionada = request.form.get("categoria", "General / Otros")
    anonimizar = request.form.get("anonimizar_datos")

    if anonimizar:
        texto_completo = anonimizar_texto_sensible(texto_completo)

    num_preguntas_test = min(20, max(10, num_paginas * 2))

    prompt_sistema = f"""
Eres LexAI Enterprise 2.0, un auditor jurídico e inmobiliario experto y tutor académico.
Analiza exhaustivamente el documento PDF adjunto clasificado en la CATEGORÍA: "{categoria_seleccionada}".

REGLAS DE GENERACIÓN SEGÚN CATEGORÍA:

1. SI LA CATEGORÍA ES "Educación / Académico":
   - "puntos_criticos_con_riesgo" debe ser un array vacío [].
   - Rellena obligatoriamente "modulo_educacion":
     * "esquema_temario": Array de cadenas de texto (strings) con la lista jerárquica y detallada de capítulos y subapartados numerados extraídos del documento (ejemplo: ["1. Título del Capítulo 1", "   1.1 Subapartado A", "   1.2 Subapartado B", "2. Título del Capítulo 2", "   2.1 Subapartado A"]).
     * "glosario": 8-10 términos técnicos con sus definiciones.
     * "preguntas_tipo_test": {num_preguntas_test} preguntas de autoevaluación con opciones y respuesta correcta.

2. PARA "Inmobiliario / Contratos" Y DEMÁS CATEGORÍAS TÉCNICO-LEGALES:
   - "modulo_educacion" debe quedar vacío: {{"esquema_temario": [], "glosario": [], "preguntas_tipo_test": []}}.
   - DEBES AUDITAR Y EXTRAER OBLIGATORIAMENTE todos los riesgos y cláusulas críticas en el array "puntos_criticos_con_riesgo".
   - Identifica específicamente: fianzas o garantías adicionales excesivas, penalizaciones por desistimiento anticipado, actualizaciones de renta, reparaciones/gastos atribuidos indebidamente al arrendatario, limitaciones de prórroga y cláusulas nulas según la Ley de Arrendamientos Urbanos (LAU) o Código Civil.
   - Cada punto de riesgo DEBE clasificar su nivel estrictamente como: "🔴 CRÍTICO", "🟡 ATENCIÓN", o "🔵 INFORMATIVO".

ESTRUCTURA JSON OBLIGATORIA DE RESPUESTA:
{{
  "categoria_documento": "{categoria_seleccionada}",
  "tipo_documento": "Tipo exacto del documento",
  "resumen_ejecutivo": "Análisis exhaustivo del documento, objeto, partes involucradas o temas principales.",
  "puntos_criticos_con_riesgo": [],
  "modulo_educacion": {{
    "esquema_temario": [
      "1. Capítulo Principal A",
      "   1.1 Subtema A.1",
      "   1.2 Subtema A.2",
      "2. Capítulo Principal B",
      "   2.1 Subtema B.1"
    ],
    "glosario": [],
    "preguntas_tipo_test": []
  }},
  "salida_accionable": "Recomendaciones estratégicas o síntesis pedagógica final.",
  "disclaimer": "Informe generado por Inteligencia Artificial para uso profesional e informativo."
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Texto del PDF a analizar:\n{texto_completo}"}
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
