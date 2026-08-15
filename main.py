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
                pdf_reader = pypdf.PdfReader(file)
                total_paginas = len(pdf_reader.pages)
                
                # Leer las primeras 15 páginas para optimizar
                max_paginas = min(total_paginas, 15)
                texto_extraido = ""
                
                for i in range(max_paginas):
                    texto_pagina = pdf_reader.pages[i].extract_text()
                    if texto_pagina:
                        texto_extraido += texto_pagina + "\n"
                
                if not texto_extraido.strip():
                    texto_extraido = "Documento escaneado sin texto digital reconocible."

                prompt_sistema = """
                Eres un Analizador Universal de Documentos impulsado por IA de nivel profesional multidisciplinar.
                Tu tarea es clasificar y analizar minuciosamente cualquier documento que recibas (Legales, Inmobiliarios, Financieros, RRHH, Médicos, Académicos, Técnicos, etc.).

                Debes responder ÚNICAMENTE con un objeto JSON válido estructurado con las siguientes claves:
                {
                  "categoria_documento": "Categoría general (Ej: Legal/Judicial, Inmobiliario/Contratos, Financiero/Facturación, Recursos Humanos, Salud/Médico, Académico/Estudio, etc.)",
                  "tipo_documento": "Nombre exacto del documento (Ej: Sentencia Penal, Contrato de Arrendamiento, Factura Simplificada, Currículum Vitae, Apuntes de Examen, Informe Clínico)",
                  "resumen_ejecutivo": "Un resumen exhaustivo, profundo y fluido adaptado a la naturaleza del documento. Explica contexto, partes o sujetos involucrados, datos clave y conclusiones.",
                  "puntos_criticos_o_riesgos": [
                    "Punto crítico, cláusula de riesgo, requisito obligatorio, habilidad destacada o hallazgo principal 1",
                    "Punto crítico o hallazgo 2",
                    "Punto crítico o hallazgo 3"
                  ],
                  "fechas_y_plazos_clave": [
                    "Plazo procesal, vencimiento de contrato, fecha de pago o hito importante 1",
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
                  "accion_o_borrador_recomendado": "Redacta una respuesta, correo, borrador procesal, contraoferta o recomendación formal según el contexto del documento."
                }

                Instrucción especial para 'preguntas_tipo_test':
                - Si el documento es académico, un libro, manual, examen o apuntes de estudio, GENERA OBLIGATORIAMENTE 3 a 5 preguntas tipo test útiles para autoevaluación.
                - Si el documento NO es académico (es una factura, nómina, etc.), puedes dejar el array vacio [] o generar 1-2 preguntas de comprobación de lectura.
                """

                api_key = os.environ.get("OPENAI_API_KEY", "").strip()
                if not api_key:
                    raise ValueError("No se ha configurado la clave OPENAI_API_KEY en Render.")

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }

                payload = {
                    "model": "gpt-4o",
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": prompt_sistema},
                        {"role": "user", "content": f"Documento a analizar ({total_paginas} páginas totales):\n\n{texto_extraido[:14000]}"}
                    ],
                    "temperature": 0.2
                }

                response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
                response_json = response.json()

                if response.status_code != 200:
                    error_msg = response_json.get("error", {}).get("message", "Error desconocido en OpenAI")
                    raise Exception(f"OpenAI API Error ({response.status_code}): {error_msg}")

                contenido = response_json["choices"][0]["message"]["content"]
                data = json.loads(contenido)

                if total_paginas > 15:
                    data["tipo_documento"] += f" ({total_paginas} págs. - Primeras 15 analizadas)"

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
