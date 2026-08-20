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

    # Cálculo escalar de preguntas para educación
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
   - Rellena obligatoriamente "modulo_educacion":
     * "esquema_temario": Array de cadenas de texto (strings) con la lista jerárquica y detallada de capítulos y subapartados numerados extraídos del documento.
     * "glosario": Array de 8 a 10 objetos, cada uno estrictamente con "termino" y "definicion".
     * "preguntas_tipo_test": Genera OBLIGATORIAMENTE {num_preguntas_test} preguntas de autoevaluación con sus 4 opciones (A, B, C, D), letra de respuesta correcta y explicación.

================================================================================
2. PARA "Inmobiliario / Contratos", "Legal / Judicial / Laboral", "Financiero" Y "General / Otros":
================================================================================
   - "modulo_educacion" debe quedar vacío: {{"esquema_temario": [], "glosario": [], "preguntas_tipo_test": []}}.
   
   A. DETECCIÓN AUTOMÁTICA DE SUBTIPO:
      Identifica el subtipo específico del documento dentro de estas opciones:
      - Contrato de arrendamiento de vivienda habitual
      - Contrato de arrendamiento de local comercial u otro uso distinto
      - Contrato de compraventa de inmueble
      - Contrato de arras o señal
      - Contrato de préstamo o hipoteca
      - Contrato mercantil entre empresas
      - Contrato laboral / carta de despido / finiquito
      - Sentencia o auto judicial
      - Notificación o requerimiento judicial
      - Demanda o escrito procesal
      - Factura o presupuesto comercial
      - Póliza de seguro
      - Nómina o recibo de salario
      - Otro documento (indicar cuál en el texto)
      * Si no se identifica con claridad, indica estrictamente "Documento genérico".

   B. IDENTIFICACIÓN DEL RÉGIMEN JURÍDICO APLICABLE:
      Indica de forma precisa la normativa o ley principal que aplica al subtipo (ej. Título II de la LAU arts. 6 a 28, Estatuto de los Trabajadores RD Leg. 2/2015, Ley de Contrato de Seguro 50/1980, Código Civil, Ley del IVA/IRPF, Ley Reguladora de la Jurisdicción Social, etc.).
      * OBLIGATORIO: La primera frase del "resumen_ejecutivo" DEBE empezar identificando expresamente este régimen jurídico para dar contexto legal inmediato.

   C. ADAPTACIÓN DEL ANÁLISIS DE RIESGOS ("puntos_criticos_con_riesgo"):
      Adapta las cláusulas y puntos auditados según el subtipo detectado:
      - En contratos de alquiler: fianzas, garantías, actualización de renta, duración, conservación y gastos.
      - En contratos laborales / finiquitos: causa de despido, indemnización, preaviso, horas extra, devengos.
      - En sentencias/autos: fallo, cuantías, plazos y vía de recurso aplicable.
      - En facturas/presupuestos: coherencia de importes, desglose IVA/IRPF, retenciones, vencimiento.
      - En nóminas: conceptos salariales, deducciones a la Seguridad Social e IRPF dentro de rango legal.
      Cada punto de riesgo DEBE clasificar su nivel estrictamente como: "🔴 CRÍTICO", "🟡 ATENCIÓN", o "🔵 INFORMATIVO".

   D. REGLA ESTRICTA DE CITAS LEGALES (VERIFICACIÓN 100%):
      - Cita artículos específicos ÚNICAMENTE si existe un 100% de certeza técnica de su aplicación exacta.
      - Si existe la menor duda sobre el número exacto del artículo o su redacción en el texto del documento, sustituye la cita por el texto explícito: "verificar normativa aplicable".
      - NUNCA inventes o deduzcas números de artículos o leyes.

ESTRUCTURA JSON OBLIGATORIA DE RESPUESTA:
{{
  "categoria_documento": "{categoria_seleccionada}",
  "tipo_documento": "Categoría general o clase de documento",
  "subtipo_detectado": "Subtipo específico identificado entre los 14 especificados",
  "regimen_juridico_aplicable": "Marco legal principal aplicable",
  "resumen_ejecutivo": "Empezar obligatoriamente indicando el régimen jurídico aplicable. Luego continuar con el análisis exhaustivo del documento, objeto, partes involucradas y obligaciones clave.",
  "puntos_criticos_con_riesgo": [
    {{
      "nivel": "🔴 CRÍTICO",
      "pagina": "Página X",
      "punto": "Descripción detallada del riesgo o cláusula",
      "contraste_estandar": "Normativa aplicable citando artículo exacto o 'verificar normativa aplicable'"
    }}
  ],
  "modulo_educacion": {{
    "esquema_temario": [],
    "glosario": [],
    "preguntas_tipo_test": []
  }},
  "salida_accionable": "Recomendaciones estratégicas concretas adaptadas al subtipo (ej. negociación de cláusulas, interposición de recurso, solicitud de rectificación de factura, etc.).",
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
