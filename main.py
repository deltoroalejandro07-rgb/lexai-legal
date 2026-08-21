import os
import re
import json
import base64
import io
import gc
import fitz  # PyMuPDF
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


def extraer_texto_por_vision(pdf_bytes):
    """ Convierte las páginas del PDF a imagen y las lee con el modelo de Visión de OpenAI """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        texto_vision = ""
        paginas_a_procesar = min(len(doc), 3)

        for i in range(paginas_a_procesar):
            page = doc[i]
            pix = page.get_pixmap(dpi=100)
            img_bytes = pix.tobytes("png")
            img_b64 = base64.b64encode(img_bytes).decode('utf-8')

            pix = None
            gc.collect()

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcripción literal completa y precisa de todo el texto visible en esta imagen de documento. Transcribe todo sin resumir."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{img_b64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1500
            )

            texto_pagina = response.choices[0].message.content
            if texto_pagina:
                texto_vision += f"\n--- PÁGINA {i+1} (Visión) ---\n" + texto_pagina

        doc.close()
        gc.collect()
        return texto_vision
    except Exception as e:
        print(f"Error en extracción Visión: {str(e)}")
        return f"ERROR_VISION: {str(e)}"


def verificar_exactitud_datos(texto_original, data_json):
    if not data_json or not texto_original:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}
    
    texto_ia = str(data_json.get("resumen_ejecutivo", "")) + " " + json.dumps(data_json.get("puntos_criticos_con_riesgo", []))
    cifras_encontradas = re.findall(r'\b\d+(?:[\.,]\d+)*(?:%|€|\$)?\b', texto_ia)
    cifras_filtradas = [c for c in cifras_encontradas if len(re.sub(r'\D', '', c)) > 0]

    if not cifras_filtradas:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}

    texto_orig_limpio = " ".join(texto_original.split())
    validadas = 0
    cifras_unicas = list(set(cifras_filtradas))

    for cifra in cifras_unicas:
        cifra_limpia = cifra.replace("€", "").replace("%", "").strip()
        if cifra in texto_original or cifra_limpia in texto_original or cifra_limpia in texto_orig_limpio:
            validadas += 1

    total = len(cifras_unicas)
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
        pdf_bytes = file.read()
        
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        num_paginas = len(doc)

        if num_paginas > 50:
            doc.close()
            return "El documento supera el límite de 50 páginas.", 400

        texto_completo = ""
        for i, page in enumerate(doc):
            contenido = page.get_text()
            if contenido:
                texto_completo += f"\n--- PÁGINA {i+1} ---\n" + contenido
        doc.close()

        # Filtro estricto: contar palabras reales de castellano
        palabras_reales = re.findall(r'\b[a-zA-ZáéíóúÁÉÍÓÚñÑ]{3,}\b', texto_completo)

        # Si no hay texto nativo suficiente (menos de 150 palabras con sentido), usamos Visión
        if len(palabras_reales) < 150:
            texto_completo = extraer_texto_por_vision(pdf_bytes)
            if texto_completo.startswith("ERROR_VISION:"):
                return f"Error en procesamiento de visión: {texto_completo}", 500

        if not texto_completo.strip():
            return "No se pudo extraer texto del PDF.", 400

        texto_completo = texto_completo[:50000]

    except Exception as e:
        return f"Error al procesar el archivo PDF: {str(e)}", 500

    categoria_seleccionada = request.form.get("categoria", "General / Otros")
    anonimizar = request.form.get("anonimizar_datos")

    if anonimizar:
        texto_completo = anonimizar_texto_sensible(texto_completo)

    num_preguntas_test = min(100, max(8, round(num_paginas / 2.2)))

    prompt_sistema = f"""
Eres LexAI Enterprise 2.0, un auditor jurídico e inmobiliario experto y tutor académico.
Analiza exhaustivamente el documento PDF adjunto clasificado en la CATEGORÍA SELECCIONADA: "{categoria_seleccionada}".

REGLAS DE GENERACIÓN SEGÚN CATEGORÍA:

================================================================================
1. SI LA CATEGORÍA ES "Educación / Académico":
================================================================================
   - "puntos_criticos_con_riesgo" debe ser un array vacío [].
   - "subtipo_detectado" y "regimen_juridico_aplicable" se rellenarán como "Documento Académico / Material de Estudio" y "No aplica (Ámbito Educativo)".
   - Rellena OBLIGATORIAMENTE Y CON DETALLE "modulo_educacion":
     * "esquema_temario": Array de cadenas de texto (strings) con la lista jerárquica y detallada de capítulos y subapartados numerados basándote en el contenido real del documento.
     * "glosario": Array de 8 a 10 objetos extraídos del texto, cada uno estrictamente con "termino" y "definicion".
     * "preguntas_tipo_test": Genera OBLIGATORIAMENTE {num_preguntas_test} preguntas de autoevaluación basadas en el texto con sus 4 opciones (A, B, C, D), letra de respuesta correcta y explicación.

================================================================================
2. PARA OTRAS CATEGORÍAS ("Inmobiliario / Contratos", "Legal / Judicial / Laboral", "Financiero", "General / Otros"):
================================================================================
   - "modulo_educacion" debe quedar vacío: {{"esquema_temario": [], "glosario": [], "preguntas_tipo_test": []}}.
   
   A. DETECCIÓN AUTOMÁTICA DE SUBTIPO Y RÉGIMEN JURÍDICO.
   B. VERIFICACIÓN MATEMÁTICA EN FACTURAS/PRESUPUESTOS.
   C. ANÁLISIS DE RIESGOS CLASIFICADOS EN: "🔴 CRÍTICO", "🟡 ATENCIÓN", o "🔵 INFORMATIVO".

ESTRUCTURA JSON OBLIGATORIA DE RESPUESTA:
{{
  "categoria_documento": "{categoria_seleccionada}",
  "tipo_documento": "Categoría general o clase de documento",
  "subtipo_detectado": "Subtipo específico identificado",
  "regimen_juridico_aplicable": "Marco legal o 'No aplica (Ámbito Educativo)'",
  "resumen_ejecutivo": "Análisis exhaustivo detallando todos los conceptos, temas o importes principales.",
  "puntos_criticos_con_riesgo": [],
  "modulo_educacion": {{
    "esquema_temario": ["1. Título principal", "1.1 Subapartado..."],
    "glosario": [{{"termino": "Ejemplo", "definicion": "Explicación detallada"}}],
    "preguntas_tipo_test": [
      {{
        "pregunta": "¿...?",
        "opciones": ["A) ...", "B) ...", "C) ...", "D) ..."],
        "respuesta_correcta": "A",
        "explicacion": "Explicación basada en el texto"
      }}
    ]
  }},
  "salida_accionable": "Recomendaciones concretas de estudio o actuación.",
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
            temperature=0.1
        )

        json_raw = response.choices[0].message.content
        data = json.loads(json_raw)

        exactitud = verificar_exactitud_datos(texto_completo, data)
        data["verificacion_exactitud"] = exactitud

        return render_template('resultado.html', data=data)

    except Exception as e:
        return f"Error en el proceso de análisis de IA: {str(e)}", 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
