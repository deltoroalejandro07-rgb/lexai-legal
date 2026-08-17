import os
import re
import json
import pypdf
from flask import Flask, request, render_template
import openai

app = Flask(__name__)

# Configuración API Key OpenAI
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY


def anonimizar_texto_sensible(texto):
    """Enmascara datos sensibles como DNI, NIE, emails y teléfonos."""
    if not texto:
        return texto
    # DNI/NIE
    texto = re.sub(r'\b[XYZxyz]?\d{7,8}[A-Za-z]\b', '[DNI/NIE ANONIMIZADO]', texto)
    # Emails
    texto = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '[EMAIL ANONIMIZADO]', texto)
    # Teléfonos España
    texto = re.sub(r'(\+34|0034)?\s*[6789]\d{2}\s*\d{3}\s*\d{3}', '[TELÉFONO ANONIMIZADO]', texto)
    return texto


def verificar_exactitud_datos(texto_original, resumen_generado):
    """Verifica que las cifras e importes citados existan en el texto original."""
    if not resumen_generado or not texto_original:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}
    
    # Extrae patrones numéricos como importes, años, porcentajes
    cifras_encontradas = re.findall(r'\b\d+(?:[\.,]\d+)?\b', resumen_generado)
    if not cifras_encontradas:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}

    validadas = 0
    for cifra in cifras_encontradas:
        if cifra in texto_original:
            validadas += 1

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

    # 1. VALIDACIÓN Y LECTURA DEL PDF
    if 'file' not in request.files:
        return "No se ha subido ningún archivo.", 400

    file = request.files['file']
    if file.filename == '':
        return "No se ha seleccionado ningún archivo.", 400

    try:
        reader = pypdf.PdfReader(file)
        num_paginas = len(reader.pages)

        # Control de límite de 50 páginas
        if num_paginas > 50:
            return (
                f"<div style='font-family: sans-serif; padding: 40px; text-align: center; color: #721c24; background-color: #f8d7da; border-radius: 8px; max-width: 600px; margin: 50px auto; border: 1px solid #f5c6cb;'>"
                f"<h2>⚠️ Documento demasiado extenso</h2>"
                f"<p>El archivo subido tiene <strong>{num_paginas} páginas</strong>. El límite máximo permitido por análisis es de <strong>50 páginas</strong>.</p>"
                f"<p>Por favor, divide el documento en partes o sube una versión resumida para proceder.</p>"
                f"<a href='/' style='display: inline-block; margin-top: 15px; padding: 10px 20px; background-color: #721c24; color: white; text-decoration: none; border-radius: 5px;'>← Volver al inicio</a>"
                f"</div>"
            ), 400

        # Extracción de texto
        texto_completo = ""
        for i, page in enumerate(reader.pages):
            contenido_pagina = page.extract_text()
            if contenido_pagina:
                texto_completo += f"\n--- PÁGINA {i+1} ---\n" + contenido_pagina

        if not texto_completo.strip():
            return "No se pudo extraer texto seleccionable del PDF. Es posible que sea un PDF escaneado (imagen).", 400

        # Límite de seguridad de caracteres (90.000 caracteres max)
        texto_completo = texto_completo[:90000]

    except Exception as e:
        return f"Error al procesar el archivo PDF: {str(e)}", 500

    # 2. CAPTURA DE PARÁMETROS DEL FORMULARIO
    categoria_seleccionada = request.form.get("categoria", "General / Otros")
    anonimizar = request.form.get("anonimizar_datos")

    # Modificación por privacidad
    if anonimizar:
        texto_completo = anonimizar_texto_sensible(texto_completo)

    # Cálculo dinámico de preguntas para Educación
    num_preguntas_test = min(20, max(10, num_paginas * 2))

    # 3. PROMPT PARA LA IA
    prompt_sistema = f"""
Eres LexAI Enterprise 2.0, una IA experta en consultoría y auditoría legal, financiera y académica.
Debes analizar el documento PDF adjunto teniendo en cuenta que pertenece a la CATEGORÍA: "{categoria_seleccionada}".

REGLAS ESPECÍFICAS SEGÚN CATEGORÍA:

1. SI LA CATEGORÍA ES "Educación / Académico":
   - "puntos_criticos_con_riesgo" DEBE ESTAR VACÍO [].
   - Rellena obligatoriamente "modulo_educacion":
     a) "resumen_esquematico": Extrae entre 5 y 8 secciones clave del temario con su título y resumen.
     b) "glosario": 8 a 10 conceptos o términos clave definidos concisamente.
     c) "preguntas_tipo_test": Genera EXACTAMENTE {num_preguntas_test} preguntas tipo test de autoevaluación.
        - Cada pregunta debe tener 4 opciones ["a)", "b)", "c)", "d)"].
        - "respuesta_correcta": La opción exacta.
        - "explicacion_detallada": Máximo 1 FRASE explicando por qué es correcta.

2. SI LA CATEGORÍA ES DE RIESGOS / LEGAL / INMOBILIARIO / FINANCIERO / GENERAL:
   - Identifica objetivamente a las partes involucradas y analiza el contrato o documento completo.
   - Analiza cláusulas abusivas, penalizaciones, fechas de vencimiento, discrepancias financieras o riesgos legales en "puntos_criticos_con_riesgo".
   - Cita la legislación aplicable siempre que sea oportuno.
   - Deja los arrays de "modulo_educacion" vacíos [].

FORMATO DE RESPUESTA JSON OBLIGATORIO:
{{
  "categoria_documento": "{categoria_seleccionada}",
  "tipo_documento": "Identificación exacta del tipo de archivo",
  "resumen_ejecutivo": "Síntesis técnica y estructurada del documento.",
  "puntos_criticos_con_riesgo": [
    {{
      "nivel": "🔴 CRÍTICO / 🟡 ADVERTENCIA / 🔵 INFORMATIVO",
      "pagina": "Página X",
      "punto": "Cláusula o hecho analizado",
      "contraste_estandar": "Riesgo legal, penalización o marco normativo relevante"
    }}
  ],
  "modulo_educacion": {{
    "resumen_esquematico": [
      {{ "titulo": "Tema/Capítulo", "resumen_seccion": "Explicación" }}
    ],
    "glosario": [
      {{ "termino": "Concepto", "definicion": "Definición corta" }}
    ],
    "preguntas_tipo_test": [
      {{
        "pregunta": "Pregunta...",
        "opciones": ["a) ...", "b) ...", "c) ...", "d) ..."],
        "respuesta_correcta": "a) ...",
        "explicacion_detallada": "Explicación en una sola frase."
      }}
    ]
  }},
  "salida_accionable": "Dictamen final, recomendación o plan de acción según el análisis.",
  "disclaimer": "Informe generado por Inteligencia Artificial para fines informativos y de apoyo profesional."
}}
"""

    try:
        response = openai.ChatCompletion.create(
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

        # Auditoría de Cifras
        exactitud = verificar_exactitud_datos(texto_completo, data.get("resumen_ejecutivo", ""))
        data["verificacion_exactitud"] = exactitud

        return render_template('resultado.html', data=data)

    except Exception as e:
        return f"Error en el proceso de análisis de IA: {str(e)}", 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
