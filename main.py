import os
import json
import requests
from flask import Flask, render_template, request
import pypdf

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if "file" not in request.files:
            return "No se ha subido ningún archivo.", 400
        
        file = request.files["file"]
        if file.filename == "":
            return "No se ha seleccionado ningún archivo.", 400
        
        # Recuperar el rol del usuario opcional seleccionado en la interfaz
        rol_usuario = request.form.get("rol_usuario", "General / Neutro")
        
        if file:
            try:
                api_key = os.environ.get("OPENAI_API_KEY", "").strip()
                if not api_key:
                    raise ValueError("No se ha configurado la clave OPENAI_API_KEY en Render.")

                pdf_reader = pypdf.PdfReader(file)
                total_paginas = len(pdf_reader.pages)
                
                texto_extraido = ""
                
                # Muestreo inteligente optimizado (evita timeouts)
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
                Eres LexAI Multi 2.0, una plataforma avanzada de Inteligencia Documental y Asesoría Automatizada.
                Analizarás el documento considerando la posición o ROL DEL USUARIO: "{rol_usuario}".

                EVALUACIÓN POR CATEGORÍAS Y ESPECIFICACIONES:
                1. INMOBILIARIO/CONTRATOS: Detecta cláusulas abusivas vs estándar del mercado español, calcula el coste total inicial (renta + fianza + gastos/IBI/comunidad) e identifica quién asume cada mantenimiento.
                2. LEGAL/JUDICIAL: Prioriza la extracción del FALLO / RESOLUCIÓN y PLAZOS DE RECURSO como urgentes. Traduce lenguaje procesal a lenguaje sencillo. AÑADE UN AVISO DE QUE NO SUSTITUYE A UN ABOGADO.
                3. FINANCIERO: Verifica que Base + IVA = Total. Destaca discrepancias o errores de cálculo y fechas de vencimiento.
                4. RRHH: En nóminas/contratos evalúa deducciones, periodo de prueba, cláusulas de no competencia y despido.
                5. SALUD Y SEGUROS: Traduce términos médicos a lenguaje llano. En pólizas, contrasta claramente cubierto vs excluido (carencias/límites ocultos). AÑADE AVISO DE CONSULTAR A UN MÉDICO.
                6. EDUCACIÓN/ESTUDIO: Activa el modo didáctico con resumen esquemático, glosario de términos y 3 a 5 preguntas tipo test A/B/C/D.

                ESTRUCTURA DE RESPUESTA REQUERIDA (OBLIGATORIAMENTE JSON VÁLIDO):
                {{
                  "categoria_documento": "Legal/Judicial | Inmobiliario/Contratos | Financiero/Facturación | Recursos Humanos | Salud/Seguros | Educación/Académico | General",
                  "tipo_documento": "Nombre exacto del tipo de archivo",
                  "resumen_ejecutivo": "Explicación fluida y rigurosa en lenguaje llano adaptada al rol seleccionado, incluyendo el fallo/resolución principal si aplica.",
                  "puntos_criticos_con_riesgo": [
                    {{
                      "nivel": "🔴 CRÍTICO | 🟡 REVISAR | 🟢 NORMAL",
                      "punto": "Descripción del hallazgo o cláusula",
                      "pagina": "Ej: Pág. 3",
                      "contraste_estandar": "Comparación breve con el estándar del sector/mercado"
                    }}
                  ],
                  "fechas_y_plazos_urgentes": [
                    {{
                      "concepto": "Descripción del plazo o hito",
                      "fecha": "Fecha exacta o plazo de días",
                      "es_urgente": true
                    }}
                  ],
                  "modulo_educacion": {{
                    "resumen_esquematico": ["Punto clave 1", "Punto clave 2"],
                    "glosario": [{{"termino": "Término", "definicion": "Explicación sencilla"}}],
                    "preguntas_tipo_test": [
                      {{
                        "pregunta": "¿Pregunta sobre el texto?",
                        "opciones": ["A) Opción 1", "B) Opción 2", "C) Opción 3", "D) Opción 4"],
                        "respuesta_correcta": "Opción exacta",
                        "explicacion": "Explicación didáctica"
                      }}
                    ]
                  }},
                  "salida_accionable": "Recomendación concreta de próximos pasos, lista de preguntas para la otra parte o borrador formal según el rol del usuario.",
                  "disclaimer": "Texto legal/médico de advertencia si aplica al documento, o cadena vacía."
                }}

                REGLAS ESTRICTAS:
                - Incluye la etiqueta de página [Ej: Pág. X] en los puntos críticos si es identificable en el texto.
                - Si el documento NO es Educación/Académico, deja el objeto "modulo_educacion" con arrays vacíos: {{"resumen_esquematico": [], "glosario": [], "preguntas_tipo_test": []}}.
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
                        {"role": "user", "content": f"Documento ({total_paginas} págs.) analizado para el Rol: {rol_usuario}:\n\n{texto_extraido[:85000]}"}
                    ],
                    "temperature": 0.1
                }

                response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
                response_json = response.json()

                if response.status_code != 200:
                    error_msg = response_json.get("error", {}).get("message", "Error en OpenAI")
                    raise Exception(f"OpenAI API Error ({response.status_code}): {error_msg}")

                contenido = response_json["choices"][0]["message"]["content"]
                data = json.loads(contenido)
                data["tipo_documento"] += f" ({total_paginas} págs. analizadas)"
                data["rol_analizado"] = rol_usuario

                return render_template("resultado.html", data=data)

            except Exception as e:
                error_data = {
                    "categoria_documento": "Error",
                    "tipo_documento": "Error en procesamiento",
                    "resumen_ejecutivo": f"No se pudo completar el análisis avanzado: {str(e)}",
                    "puntos_criticos_con_riesgo": [],
                    "fechas_y_plazos_urgentes": [],
                    "modulo_educacion": {"resumen_esquematico": [], "glosario": [], "preguntas_tipo_test": []},
                    "salida_accionable": "Inténtelo de nuevo o verifique la validez del archivo PDF.",
                    "disclaimer": ""
                }
                return render_template("resultado.html", data=error_data)

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
