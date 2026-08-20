import os
import re
import json
import base64
import io
import pypdf
from PIL import Image
from pdf2image import convert_from_bytes
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


def extraer_texto_ocr_vision(pdf_bytes):
    """
    Convierte las páginas del PDF escaneado a imágenes y utiliza OpenAI Vision
    para extraer todo el texto del documento.
    """
    try:
        images = convert_from_bytes(pdf_bytes)
        texto_ocr = ""

        # Limitamos el procesado visual a las primeras 15 páginas por rendimiento
        for i, img in enumerate(images[:15]):
            buffered = io.BytesIO()
            img.save(buffered, format="JPEG")
            img_b64 = base64.b64encode(buffered.getvalue()).decode('utf-8')

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Transcripción literal completa y precisa de todo el texto de esta imagen de un documento. No resumas, transcribe todo el texto visible."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{img_b64}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000
            )

            texto_pagina = response.choices[0].message.content
            if texto_pagina:
                texto_ocr += f"\n--- PÁGINA {i+1} (OCR Vision) ---\n" + texto_pagina

        return texto_ocr
    except Exception as e:
        print(f"Error en extracción OCR con Vision: {str(e)}")
        return ""


def verificar_exactitud_datos(texto_original, data_json):
    """
    Extrae y contrasta las cifras numéricas presentes tanto en el Resumen Ejecutivo
    como en la Auditoría de Riesgos contra el texto original extraído del PDF.
    """
    if not data_json or not texto_original:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}
    
    # Concatenamos todo el texto generado por la IA donde hay datos numéricos
    texto_ia = str(data_json.get("resumen_ejecutivo", "")) + " " + json.dumps(data_json.get("puntos_criticos_con_riesgo", []))

    # Regex mejorada para capturar números, importes, porcentajes y cifras decimales (formato ES y EN)
    cifras_encontradas = re.findall(r'\b\d+(?:[\.,]\d+)*(?:%|€|\$)?\b', texto_ia)
    
    # Filtramos cifras irrelevantes muy cortas
    cifras_filtradas = [c for c in cifras_encontradas if len(re.sub(r'\D', '', c)) > 0]

    if not cifras_filtradas:
        return {"score_exactitud": 100, "cifras_validadas": 0, "total_cifras_verificadas": 0}

    # Normalizamos el texto original quitando espacios raros para facilitar la búsqueda de la cifra
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
        file_stream = io.BytesIO(pdf_bytes)

        reader = pypdf.PdfReader(file_stream)
        num_paginas = len(reader.pages)

        if num_paginas > 50:
            return "El documento supera el límite de 50 páginas.", 400

        texto_completo = ""
        for i, page in enumerate(reader.pages):
            contenido = page.extract_text()
            if contenido:
                texto_completo += f"\n--- PÁGINA {i+1} ---\n" + contenido

        # FALLBACK SI ES UN PDF ESCANEADO / IMAGEN
        if not texto_completo.strip():
            texto_completo = extraer_texto_ocr_vision(pdf_bytes)

        if not texto_completo.strip():
            return "No se pudo extraer texto del PDF (el archivo podría estar en blanco o dañado).", 400

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
     * "esquema_temario": Array de cadenas de texto (strings) con la lista jerárquica y detallada de capítulos y subapartados numerados.
     * "glosario": Array de 8 a 10 objetos, cada uno strictly con "termino" y "definicion".
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
      Indica de forma precisa la normativa o ley principal que aplica al subtipo.
      * OBLIGATORIO: La primera frase del "resumen_ejecutivo" DEBE empezar identificando expresamente este régimen jurídico para dar contexto legal inmediato.

   C. VERIFICACIÓN MATEMÁTICA Y AUDITORÍA DE FACTURAS Y PRESUPUESTOS (REGLA IMPERATIVA):
      Si el subtipo es "Factura o presupuesto comercial":
      1. Extrae explícitamente en el "resumen_ejecutivo" todas las cifras: Base Imponible, tipos de IVA/IRPF aplicados, importes de impuestos y Total a Pagar.
      2. CALCULA Y VERIFICA MATEMÁTICAMENTE: Suma la Base Imponible + Impuestos (IVA) - Retenciones (IRPF).
      3. Compara tu resultado calculado con el Total a Pagar impreso en el documento.
      4. SI HAY UN DESCUADRE O ERROR MATEMÁTICO, DEBES GENERAR OBLIGATORIAMENTE UN PUNTO EN "puntos_criticos_con_riesgo" CON NIVEL "🔴 CRÍTICO" USANDO ESTE FORMATO EXACTO:
         "Error Matemático / Descuadre en Total a Pagar: La suma de la Base Imponible ([importe base]) y los impuestos ([importe impuestos]) debería ser [suma calculada correcta], no [total que aparece en el documento]. Hay una diferencia de [importe descuadre]."

   D. ADAPTACIÓN DEL ANÁLISIS DE RIESGOS EN OTROS SUBTIPOS:
      - En contratos de alquiler: fianzas, garantías, actualización de renta, duración, conservación y gastos.
      - En contratos laborales / finiquitos: causa de despido, indemnización, preaviso, horas extra, devengos.
      - En sentencias/autos: fallo, cuantías, plazos y vía de recurso aplicable.
      - En nóminas: conceptos salariales, deducciones a la Seguridad Social e IRPF.
      Cada punto de riesgo DEBE clasificar su nivel estrictamente como: "🔴 CRÍTICO", "🟡 ATENCIÓN", o "🔵 INFORMATIVO".

   E. REGLA ESTRICTA DE CITAS LEGALES (VERIFICACIÓN 100%):
      - Cita artículos específicos ÚNICAMENTE si existe un 100% de certeza técnica de su aplicación exacta.
      - Si existe la menor duda sobre el número exacto del artículo o su redacción en el texto del documento, sustituye la cita por el texto explícito: "verificar normativa aplicable".
      - NUNCA inventes o deduzcas números de artículos o leyes.

ESTRUCTURA JSON OBLIGATORIA DE RESPUESTA:
{{
  "categoria_documento": "{categoria_seleccionada}",
  "tipo_documento": "Categoría general o clase de documento",
  "subtipo_detectado": "Subtipo específico identificado entre los 14 especificados",
  "regimen_juridico_aplicable": "Marco legal principal aplicable",
  "resumen_ejecutivo": "Empezar obligatoriamente indicando el régimen jurídico aplicable. Luego continuar con el análisis exhaustivo detallando todos los datos e importes principales.",
  "puntos_criticos_con_riesgo": [
    {{
      "nivel": "🔴 CRÍTICO",
      "pagina": "Página X",
      "punto": "Descripción detallada del riesgo o del error matemático con las cifras exactas",
      "contraste_estandar": "Normativa fiscal/comercial o 'verificar normativa aplicable'"
    }}
  ],
  "modulo_educacion": {{
    "esquema_temario": [],
    "glosario": [],
    "preguntas_tipo_test": []
  }},
  "salida_accionable": "Recomendaciones estratégicas concretas adaptadas al subtipo (ej. solicitar factura rectificativa por error en total, negociación de cláusulas, interposición de recurso, etc.).",
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

        # Se realiza la auditoría de cifras incluyendo tanto el resumen como la tabla de riesgos
        exactitud = verificar_exactitud_datos(texto_completo, data)
        data["verificacion_exactitud"] = exactitud

        return render_template('resultado.html', data=data)

    except Exception as e:
        return f"Error en el proceso de análisis de IA: {str(e)}", 500


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
