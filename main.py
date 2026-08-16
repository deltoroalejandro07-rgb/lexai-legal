import os
import json
import re
import io
import requests
from flask import Flask, render_template, request, make_response
import pypdf

app = Flask(__name__)

# LÍMITE MÁXIMO GLOBAL DE PÁGINAS PERMITIDAS
LIMITE_MAX_PAGINAS = 50

def verificar_exactitud_datos(texto_pdf, json_analisis):
    texto_limpio = " ".join(texto_pdf.lower().split())
    
    texto_a_verificar = json_analisis.get("resumen_ejecutivo", "") + " "
    for p in json_analisis.get("puntos_criticos_con_riesgo", []):
        texto_a_verificar += p.get("punto", "") + " "
    
    patron_cifras = r'\b(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?\s*(?:€|euros?|\$|USD|%)\b'
    cifras_encontradas = re.findall(patron_cifras, texto_a_verificar, re.IGNORECASE)
    
    total_cifras = len(cifras_encontradas)
    cifras_validadas = 0
    alucinaciones_detectadas = []

    for cifra in cifras_encontradas:
        cifra_limpia = cifra.replace(" ", "").replace("€", "").replace("euros", "").replace("euro", "").strip()
        if cifra_limpia in texto_limpio.replace(" ", ""):
            cifras_validadas += 1
        else:
            alucinaciones_detectadas.append(cifra)

    score = 100
    if total_cifras > 0:
        score = round((cifras_validadas / total_cifras) * 100)

    return {
        "score_exactitud": score,
        "total_cifras_verificadas": total_cifras,
        "cifras_validadas": cifras_validadas,
        "advertencia_alucinacion": alucinaciones_detectadas
    }

def verificar_descuadre_financiero(texto_pdf):
    texto_limpio = texto_pdf.replace(".", "").replace(",", ".")
    importes = [float(x) for x in re.findall(r'\b\d+\.\d{2}\b', texto_limpio)]
    
    if len(importes) >= 3:
        for i in range(len(importes)):
            for j in range(len(importes)):
                if i == j: continue
                for k in range(len(importes)):
                    if k == i or k == j: continue
                    a, b, c = importes[i], importes[j], importes[k]
                    if abs((a + b) - c) > 0.05 and abs((a + b) - c) < 50000:
                        if c > (a + b) and abs(c - (a + b)) > 1:
                            diferencia = round(c - (a + b), 2)
                            return {
                                "hay_descuadre": True,
                                "base_impuestos": round(a + b, 2),
                                "total_declarado": round(c, 2),
                                "diferencia": diferencia
                            }
    return {"hay_descuadre": False}

def anonimizar_texto_sensible(texto):
    if not texto: return ""
    texto = re.sub(r'\b[0-9]{8}[A-Z]\b', '***REDACTADO_DNI***', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\b[XYZ][0-9]{7}[A-Z]\b', '***REDACTADO_NIE***', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '***EMAIL_PROTEGIDO***', texto)
    texto = re.sub(r'\b(?:\+34\s?)?[6789]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b', '***TEL_PROTEGIDO***', texto)
    return texto

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "file" not in request.files:
            return "No se ha subido ningún archivo.", 400
        
        file = request.files["file"]
        if file.filename == "":
            return "No se ha seleccionado ningún archivo.", 400
        
        rol_usuario = request.form.get("rol_usuario", "General / Neutro")
        anonimizar = request.form.get("anonimizar_datos") == "on"
        
        if file:
            try:
                api_key = os.environ.get("OPENAI_API_KEY", "").strip()
                if not api_key:
                    raise ValueError("No se ha configurado la clave OPENAI_API_KEY en Render.")

                file_stream = io.BytesIO(file.read())
                pdf_reader = pypdf.PdfReader(file_stream)
                total_paginas = len(pdf_reader.pages)
                
                # COMPROBACIÓN DE LÍMITE MÁXIMO DE 50 PÁGINAS
                if total_paginas > LIMITE_MAX_PAGINAS:
                    mensaje_exceso = (
                        f"Este documento tiene {total_paginas} páginas y supera nuestro límite actual de {LIMITE_MAX_PAGINAS} páginas por análisis. "
                        f"Para procesarlo, divide el PDF en partes de máximo {LIMITE_MAX_PAGINAS} páginas cada una y súbelas por separado. "
                        f"Puedes dividir el PDF fácilmente con herramientas gratuitas como ilovepdf.com o smallpdf.com, o usando 'Vista Previa' en Mac."
                    )
                    
                    error_data = {
                        "categoria_documento": "Aviso de Tamaño",
                        "tipo_documento": f"Documento Excedido ({total_paginas} págs.)",
                        "resumen_ejecutivo": mensaje_exceso,
                        "puntos_criticos_con_riesgo": [],
                        "fechas_y_plazos_urgentes": [],
                        "modulo_educacion": {"resumen_esquematico": [], "glosario": [], "preguntas_tipo_test": []},
                        "salida_accionable": "Divide el archivo e inténtalo de nuevo.",
                        "verificacion_exactitud": {"score_exactitud": 100, "total_cifras_verificadas": 0, "cifras_validadas": 0, "advertencia_alucinacion": []},
                        "disclaimer": "Límite de páginas alcanzado."
                    }
                    return render_template("resultado.html", data=error_data)

                texto_extraido = ""
                for i in range(total_paginas):
                    texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")

                if not texto_extraido.strip():
                    texto_extraido = "Documento escaneado sin texto digital reconocible."

                # AJUSTADO HASTA 30 PREGUNTAS MÁXIMO
                num_preguntas_test = min(30, max(10, total_paginas * 3 // 5))

                prompt_sistema = f"""
                Eres LexAI Enterprise 2.0, profesor y tutor académico de máximo nivel universitario.
                Analizarás el documento considerando la posición o ROL DEL USUARIO: "{rol_usuario}".

                INSTRUCCIONES ESPECÍFICAS SEGÚN CATEGORÍA:

                1. CATEGORÍA "Educación/Académico" (Apuntes, libros, artículos, temarios):
                   - NO GENERAR RIESGOS NI CLÁUSULAS CRÍTICAS. Dejar "puntos_criticos_con_riesgo" VACÍO [].
                   - Genera dentro del objeto "modulo_educacion":
                     a) "resumen_esquematico": Identifica y selecciona los 6 a 10 APARTADOS O CONCEPTOS MÁS IMPORTANTES Y RELEVANTES del temario. Para cada uno, genera un objeto con "titulo" y "resumen_seccion". El "resumen_seccion" DEBE SER UN RESUMEN AMPLIO, EXTENSO Y PROFUNDO DE 2 A 3 PÁRRAFOS COMPLETOS (mínimo 10-15 líneas por apartado), explicando con el mayor detalle pedagógico posible las ideas clave, fórmulas, normativas o teorías esenciales para que sirva directamente como material de estudio para un examen.
                     b) "glosario": 8 a 12 términos técnicos más importantes con sus definiciones pedagógicas exhaustivas.
                     c) "preguntas_tipo_test": DEBES GENERAR EXACTAMENTE {num_preguntas_test} preguntas tipo test académicas distribuidas de forma equitativa por todo el contenido. Cada objeto debe tener: 'id', 'pregunta', 'opciones' (4 opciones), 'respuesta_correcta' (A, B, C o D) y 'explicacion_detallada'.

                2. OTRAS CATEGORÍAS (Inmobiliario, Financiero, Legal, Laboral):
                   - Evaluar cláusulas, leyes imperativas o descuadres numéricos en "puntos_criticos_con_riesgo".
                   - Dejar "modulo_educacion" con arrays vacíos.

                ESTRUCTURA DE RESPUESTA REQUERIDA (JSON VÁLIDO):
                {{
                  "categoria_documento": "Educación/Académico | Inmobiliario/Contratos | Financiero/Facturación | Legal/Judicial | Recursos Humanos | Salud/Seguros | General",
                  "tipo_documento": "Tipo exacto del archivo",
                  "resumen_ejecutivo": "Visión general pedagógica y marco sintético completo del documento académico.",
                  "puntos_criticos_con_riesgo": [],
                  "modulo_educacion": {{
                    "resumen_esquematico": [
                      {{
                        "titulo": "1. Título del Tema Clave", 
                        "resumen_seccion": "Primer párrafo amplio desarrollando los conceptos centrales y definiciones fundamentales...\n\nSegundo párrafo explicando las implicaciones prácticas, fórmulas o casos particulares..."
                      }}
                    ],
                    "glosario": [
                      {{"termino": "Concepto", "definicion": "Definición profunda."}}
                    ],
                    "preguntas_tipo_test": []
                  }},
                  "fechas_y_plazos_urgentes": [],
                  "salida_accionable": "Plan de estudio recomendado para asimilar el temario de forma óptima.",
                  "disclaimer": "Este material ha sido procesado automáticamente con fines educativos."
                }}
                """

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": "gpt-4o-mini",
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": prompt_sistema},
                        {"role": "user", "content": f"Documento ({total_paginas} págs.) para Rol {rol_usuario}:\n\n{texto_extraido[:100000]}"}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 6000
                }

                response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=90)
                response_json = response.json()

                if response.status_code != 200:
                    error_msg = response_json.get("error", {}).get("message", "Error en OpenAI")
                    raise Exception(f"OpenAI API Error ({response.status_code}): {error_msg}")

                contenido = response_json["choices"][0]["message"]["content"]
                data = json.loads(contenido)
                
                if "modulo_educacion" not in data:
                    data["modulo_educacion"] = {"resumen_esquematico": [], "glosario": [], "preguntas_tipo_test": []}

                verificacion = verificar_exactitud_datos(texto_extraido, data)
                data["verificacion_exactitud"] = verificacion

                if "Financiero" in data.get("categoria_documento", ""):
                    descuadre = verificar_descuadre_financiero(texto_extraido)
                    if descuadre.get("hay_descuadre"):
                        data.setdefault("puntos_criticos_con_riesgo", []).insert(0, {
                            "nivel": "🔴 CRÍTICO",
                            "punto": f"Discrepancia y error de cálculo aritmético: La suma de Base Imponible + Impuestos resulta en {descuadre['base_impuestos']}€, pero el TOTAL A PAGAR indicado en el documento es de {descuadre['total_declarado']}€ (diferencia no justificada de {descuadre['diferencia']}€).",
                            "pagina": "Pág. 1",
                            "contraste_estandar": "Normativa de Facturación (Suma de Base + IVA)"
                        })

                if anonimizar:
                    data["resumen_ejecutivo"] = anonimizar_texto_sensible(data.get("resumen_ejecutivo", ""))
                    data["salida_accionable"] = anonimizar_texto_sensible(data.get("salida_accionable", ""))

                data["tipo_documento"] = data.get("tipo_documento", "Documento") + f" ({total_paginas} págs. analizadas)"
                data["rol_analizado"] = rol_usuario

                del file_stream
                del texto_extraido

                resp = make_response(render_template("resultado.html", data=data))
                resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
                resp.headers["Pragma"] = "no-cache"
                return resp

            except Exception as e:
                error_data = {
                    "categoria_documento": "Error",
                    "tipo_documento": "Error en procesamiento",
                    "resumen_ejecutivo": f"No se pudo completar el análisis: {str(e)}",
                    "puntos_criticos_con_riesgo": [],
                    "fechas_y_plazos_urgentes": [],
                    "modulo_educacion": {"resumen_esquematico": [], "glosario": [], "preguntas_tipo_test": []},
                    "salida_accionable": "Inténtelo de nuevo.",
                    "verificacion_exactitud": {"score_exactitud": 0, "total_cifras_verificadas": 0, "cifras_validadas": 0, "advertencia_alucinacion": []},
                    "disclaimer": ""
                }
                return render_template("resultado.html", data=error_data)

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
