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
    
    # 1. Extraer importes económicos ($ / € / EUR) del resumen y puntos críticos
    texto_a_verificar = json_analisis.get("resumen_ejecutivo", "") + " "
    for p in json_analisis.get("puntos_criticos_con_riesgo", []):
        texto_a_verificar += p.get("punto", "") + " "
    
    # Buscar cifras monetarias (ej: 1.150,00 €, 3058505,22, 10%)
    patron_cifras = r'\b(?:\d{1,3}(?:\.\d{3})+|\d+)(?:,\d{1,2})?\s*(?:€|euros?|\$|USD|%)\b'
    cifras_encontradas = re.findall(patron_cifras, texto_a_verificar, re.IGNORECASE)
    
    total_cifras = len(cifras_encontradas)
    cifras_validadas = 0
    alucinaciones_detectadas = []

    for cifra in cifras_encontradas:
        # Limpiar la cifra para búsqueda aproximada
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
    # Enmascarar DNI/NIE
    texto = re.sub(r'\b[0-9]{8}[A-Z]\b', '***REDACTADO_DNI***', texto, flags=re.IGNORECASE)
    texto = re.sub(r'\b[XYZ][0-9]{7}[A-Z]\b', '***REDACTADO_NIE***', texto, flags=re.IGNORECASE)
    # Enmascarar Emails
    texto = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '***EMAIL_PROTEGIDO***', texto)
    # Enmascarar Teléfonos (9 dígitos)
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

                # GESTIÓN CONFIDENCIAL: Procesamiento 100% en Memoria RAM (BytesIO)
                # El archivo NUNCA se guarda en el disco duro del servidor.
                file_stream = io.BytesIO(file.read())
                pdf_reader = pypdf.PdfReader(file_stream)
                total_paginas = len(pdf_reader.pages)
                
                texto_extraido = ""
                
                # Muestreo inteligente de páginas
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
                Eres LexAI Enterprise 2.0, motor de Inteligencia Documental con certificación de precisión y confidencialidad.
                Analizarás el documento para el ROL DEL USUARIO: "{rol_usuario}".

                REGLA DE PRECISIÓN DE DATOS:
                - Sé extremadamente estricto al citar cifras, fechas, plazos e importes monetarios. Cita SOLO cifras explícitas en el texto.
                
                ESTRUCTURA DE RESPUESTA EN JSON VÁLIDO:
                {{
                  "categoria_documento": "Legal/Judicial | Inmobiliario/Contratos | Financiero/Facturación | Recursos Humanos | Salud/Seguros | Educación/Académico | General",
                  "tipo_documento": "Nombre exacto del tipo de archivo",
                  "resumen_ejecutivo": "Explicación fluida y rigurosa adaptada al rol seleccionado, incluyendo fallo/resolución.",
                  "puntos_criticos_con_riesgo": [
                    {{
                      "nivel": "🔴 CRÍTICO | 🟡 REVISAR | 🟢 NORMAL",
                      "punto": "Descripción del hallazgo o cláusula",
                      "pagina": "Ej: Pág. 3",
                      "contraste_estandar": "Comparación breve con el estándar del mercado"
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
                  "salida_accionable": "Recomendación concreta, borrador o próximos pasos según el rol.",
                  "disclaimer": "Aviso legal/médico preventivo si aplica."
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
                    "temperature": 0.0 # Temperatura cero para máxima fidelidad
                }

                response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
                response_json = response.json()

                if response.status_code != 200:
                    error_msg = response_json.get("error", {}).get("message", "Error en OpenAI")
                    raise Exception(f"OpenAI API Error ({response.status_code}): {error_msg}")

                contenido = response_json["choices"][0]["message"]["content"]
                data = json.loads(contenido)
                
                # 8. CAPA DE VERIFICACIÓN DE EXACTITUD (Auto-chequeo)
                verificacion = verificar_exactitud_datos(texto_extraido, data)
                data["verificacion_exactitud"] = verificacion

                # 9. GESTIÓN DE DATOS SENSIBLES (Anonimización si se solicitó)
                if anonimizar:
                    data["resumen_ejecutivo"] = anonimizar_texto_sensible(data["resumen_ejecutivo"])
                    data["salida_accionable"] = anonimizar_texto_sensible(data["salida_accionable"])

                data["tipo_documento"] += f" ({total_paginas} págs. analizadas)"
                data["rol_analizado"] = rol_usuario

                # BARRIDO DE MEMORIA RAM
                del file_stream
                del texto_extraido

                # Respuesta con cabeceras de privacidad (No almacenar en caché)
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
