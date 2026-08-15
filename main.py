import os
import json
import re
import io
import requests
from flask import Flask, render_template, request, make_response
import pypdf

app = Flask(__name__)

def verificar_exactitud_datos(texto_pdf, json_analisis):
    """
    Función determinista que contrasta cifras e importes del JSON de la IA
    contra el texto original extraído del PDF para detectar posibles alucinaciones.
    """
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

def anonimizar_texto_sensible(texto):
    """Enmascara DNI/NIE, emails y teléfonos para protección de datos personales."""
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
                
                texto_extraido = ""
                
                if total_paginas <= 15:
                    for i in range(total_paginas):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")
                else:
                    texto_extraido += "=== INICIO DEL DOCUMENTO (PRIMERAS PÁGINAS) ===\n"
                    for i in range(8):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")
                    
                    texto_extraido += "\n\n=== RESUMEN PÁGINAS INTERMEDIAS ===\n"
                    paso = max(1, total_paginas // 4)
                    for i in range(8, total_paginas - 8, paso):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")
                    
                    texto_extraido += "\n\n=== PARTE FINAL DEL DOCUMENTO (ÚLTIMAS PÁGINAS - RESOLUCIÓN/FALLO) ===\n"
                    for i in range(total_paginas - 8, total_paginas):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")

                if not texto_extraido.strip():
                    texto_extraido = "Documento escaneado sin texto digital reconocible."

                prompt_sistema = f"""
                Eres LexAI Enterprise 2.0, auditor jurídico de precisión.
                Analizarás el documento considerando la posición o ROL DEL USUARIO: "{rol_usuario}".

                CAPA DE AUDITORÍA DE CUMPLIMIENTO LEGAL IMPERATIVO (SISTEMA DE VERIFICACIÓN LAU/CÓDIGO CIVIL):
                Si el documento es de categoría "Inmobiliario/Contratos" (Arrendamiento de vivienda en España), DEBES verificar de forma OBLIGATORIA e INDEPENDIENTE los siguientes 5 puntos imperativos de la Ley de Arrendamientos Urbanos (LAU), aunque el contrato intente pactar lo contrario:

                1. FIANZA LEGAL (Art. 36.1 y 36.5 LAU): La fianza exigible legalmente en vivienda habitual es de EXACTAMENTE 1 MENSUALIDAD DE RENTA. Si el contrato fija una fianza superior (ej. 2 o 3 mensualidades) sin especificar y diferenciar claramente que el exceso es una "Garantía Adicional" (limitada además a máximo 2 meses más en vivienda habitual), MÁRCALO OBLIGATORIAMENTE COMO "🔴 CRÍTICO: Ilegalidad / Exceso sobre el límite del Art. 36 LAU".
                2. ACTUALIZACIÓN DE RENTA (Art. 18 LAU): La renta solo puede actualizarse anualmente si está pactado expresamente, y NUNCA puede superar la variación del IPC/Índice legal. Pactos de subida fija automática (ej. +5% anual) son nulos. Si los hay, marca "🔴 CRÍTICO".
                3. PRÓRROGA OBLIGATORIA (Art. 9 LAU): La duración pactada inferior a 5 años (o 7 si arrendador es empresa) se prorroga obligatoriamente año a año para el arrendador. Cláusulas que nieguen la prórroga legal al inquilino son "🔴 CRÍTICO".
                4. DESISTIMIENTO Y PENALIZACIÓN (Art. 11 LAU): El inquilino puede desistir tras 6 meses. La indemnización máxima legal pactada no puede exceder de 1 mes por año restante. Exigir pagar todo el contrato restante es "🔴 CRÍTICO".
                5. OBRAS Y REPARACIONES (Art. 21 LAU): Las reparaciones de habitabilidad (caldera, tuberías, estructura) son del arrendador. Obligar al inquilino a pagarlas es "🔴 CRÍTICO".

                ESTRUCTURA DE RESPUESTA REQUERIDA (JSON VÁLIDO):
                {{
                  "categoria_documento": "Legal/Judicial | Inmobiliario/Contratos | Financiero/Facturación | Recursos Humanos | Salud/Seguros | Educación/Académico | General",
                  "tipo_documento": "Nombre exacto del tipo de archivo",
                  "resumen_ejecutivo": "Resumen claro y riguroso adaptado al rol.",
                  "puntos_criticos_con_riesgo": [
                    {{
                      "nivel": "🔴 CRÍTICO | 🟡 REVISAR | 🟢 NORMAL",
                      "punto": "Descripción detallada de la cláusula o del incumplimiento legal explícito",
                      "pagina": "Ej: Pág. 1",
                      "contraste_estandar": "Referencia explícita al artículo de la LAU/Ley incumplido o al estándar de mercado"
                    }}
                  ],
                  "fechas_y_plazos_urgentes": [
                    {{
                      "concepto": "Descripción del plazo",
                      "fecha": "Fecha exacta o días",
                      "es_urgente": true
                    }}
                  ],
                  "modulo_educacion": {{
                    "resumen_esquematico": [],
                    "glosario": [],
                    "preguntas_tipo_test": []
                  }},
                  "salida_accionable": "Acciones sugeridas o redacción corregida legalmente según el rol.",
                  "disclaimer": "Este informe es una auditoría automatizada y no sustituye el asesoramiento de un abogado colegiado."
                }}
                """

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": "gpt-4o",
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": prompt_sistema},
                        {"role": "user", "content": f"Documento ({total_paginas} págs.) para Rol {rol_usuario}:\n\n{texto_extraido[:85000]}"}
                    ],
                    "temperature": 0.0
                }

                response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
                response_json = response.json()

                if response.status_code != 200:
                    error_msg = response_json.get("error", {}).get("message", "Error en OpenAI")
                    raise Exception(f"OpenAI API Error ({response.status_code}): {error_msg}")

                contenido = response_json["choices"][0]["message"]["content"]
                data = json.loads(contenido)
                
                verificacion = verificar_exactitud_datos(texto_extraido, data)
                data["verificacion_exactitud"] = verificacion

                if anonimizar:
                    data["resumen_ejecutivo"] = anonimizar_texto_sensible(data["resumen_ejecutivo"])
                    data["salida_accionable"] = anonimizar_texto_sensible(data["salida_accionable"])

                data["tipo_documento"] += f" ({total_paginas} págs. analizadas)"
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
