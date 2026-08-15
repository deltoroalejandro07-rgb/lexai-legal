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
        
        if file:
            try:
                api_key = os.environ.get("OPENAI_API_KEY", "").strip()
                if not api_key:
                    raise ValueError("No se ha configurado la clave OPENAI_API_KEY en Render.")

                pdf_reader = pypdf.PdfReader(file)
                total_paginas = len(pdf_reader.pages)
                
                texto_extraido = ""
                
                # ESTRATEGIA INTELIGENTE DE MUESTREO:
                if total_paginas <= 20:
                    # Si tiene 20 páginas o menos, leemos absolutamente todo
                    for i in range(total_paginas):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")
                else:
                    # Si es un documento gigante (ej: 480 páginas):
                    # 1. Primeras 10 páginas (Encabezado, partes, hechos)
                    texto_extraido += "=== INICIO DEL DOCUMENTO (PRIMERAS PÁGINAS) ===\n"
                    for i in range(10):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")
                    
                    # 2. Muestra intermedia
                    texto_extraido += "\n\n=== RESUMEN DE PÁGINAS INTERMEDIAS ===\n"
                    paso = max(1, total_paginas // 5)
                    for i in range(10, total_paginas - 10, paso):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")
                    
                    # 3. ÚLTIMAS 10 PÁGINAS (¡Donde está el fallo, la condena y las conclusiones!)
                    texto_extraido += "\n\n=== PARTE FINAL DEL DOCUMENTO (ÚLTIMAS PÁGINAS - CRÍTICO: FALLO Y RESOLUCIÓN) ===\n"
                    for i in range(total_paginas - 10, total_paginas):
                        texto_extraido += f"\n--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "")

                if not texto_extraido.strip():
                    texto_extraido = "Documento escaneado sin texto digital reconocible."

                prompt_sistema = """
                Eres un Analizador Universal de Documentos impulsado por IA de nivel profesional multidisciplinar.
                Tu tarea es clasificar y analizar minuciosamente cualquier documento que recibas.

                INSTRUCCIÓN CRÍTICA DE ANÁLISIS:
                - Presta ESPECIAL ATENCIÓN a la sección "PARTE FINAL DEL DOCUMENTO", ya que allí se encuentran las conclusiones definitivas, la resolución, el fallo de la sentencia o los acuerdos finales.
                - Garantiza que la resolución o fallo final figure de forma clara y prioritaria en el resumen ejecutivo y en los puntos críticos.

                Debes responder ÚNICAMENTE con un objeto JSON válido estructurado con las siguientes claves:
                {
                  "categoria_documento": "Categoría general (Ej: Legal/Judicial, Inmobiliario/Contratos, Financiero/Facturación, Recursos Humanos, Salud/Médico, Educación/Académico, etc.)",
                  "tipo_documento": "Nombre exacto del documento (Ej: Sentencia Penal, Contrato de Arrendamiento, Factura, Currículum Vitae, Apuntes de Examen, Temario Máster, Informe Clínico)",
                  "resumen_ejecutivo": "Un resumen exhaustivo, profundo y fluido adaptado a la naturaleza del documento. Explica contexto, partes involucradas, hechos probados y OBLIGATORIAMENTE EL FALLO / RESOLUCIÓN FINAL O CONCLUSIÓN.",
                  "puntos_criticos_o_riesgos": [
                    "Punto crítico, resolución/fallo, condena, cláusula de riesgo o hallazgo principal 1",
                    "Punto crítico o hallazgo 2",
                    "Punto crítico o hallazgo 3"
                  ],
                  "fechas_y_plazos_clave": [
                    "Plazo procesal para recurso, vencimiento de contrato, fecha de pago o hito importante 1",
                    "Fecha límite o hito 2"
                  ],
                  "preguntas_tipo_test": [
                    {
                      "pregunta": "¿Pregunta de evaluación sobre el texto?",
                      "opciones": ["A) Opción 1", "B) Opción 2", "C) Opción 3", "D) Opción 4"],
                      "respuesta_correcta": "Letra y opción correcta",
                      "explicacion": "Explicación breve del motivo de la respuesta."
                    }
                  ],
                  "accion_o_borrador_recomendado": "Redacta una respuesta, correo, borrador procesal de recurso/contestación o recomendación formal según el contexto del documento."
                }

                REGLA ESTRICTA PARA 'preguntas_tipo_test':
                - SI Y SOLO SI el documento es de categoría EDUCACIÓN / ACADÉMICO, GENERA entre 3 y 5 preguntas tipo test para repaso.
                - PARA CUALQUIER OTRO TIPO DE DOCUMENTO, DEBES DEJAR ESTE ARRAY COMPLETAMENTE VACÍO: "preguntas_tipo_test": []
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
                        {"role": "user", "content": f"Documento a analizar ({total_paginas} páginas totales en el PDF original):\n\n{texto_extraido[:80000]}"}
                    ],
                    "temperature": 0.1
                }

                response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=50)
                response_json = response.json()

                if response.status_code != 200:
                    error_msg = response_json.get("error", {}).get("message", "Error desconocido en OpenAI")
                    raise Exception(f"OpenAI API Error ({response.status_code}): {error_msg}")

                contenido = response_json["choices"][0]["message"]["content"]
                data = json.loads(contenido)

                data["tipo_documento"] += f" ({total_paginas} págs. - Muestreo Inicio/Fin Completo)"

                return render_template("resultado.html", data=data)

            except Exception as e:
                error_data = {
                    "categoria_documento": "Error",
                    "tipo_documento": "Error en el análisis",
                    "resumen_ejecutivo": f"No se pudo completar el análisis. Detalle: {str(e)}",
                    "puntos_criticos_o_riesgos": ["Revisa la configuración o la clave API."],
                    "fechas_y_plazos_clave": ["N/A"],
                    "preguntas_tipo_test": [],
                    "accion_o_borrador_recomendado": "No disponible."
                }
                return render_template("resultado.html", data=error_data)

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
