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
                Eres un abogado senior experto. Analiza el documento procesal/legal y responde ÚNICAMENTE con un objeto JSON válido con este formato:
                {
                  "tipo_documento": "Tipo exacto de documento (Ej: Sentencia Penal, Notificación de Embargo, Contrato de Arrendamiento)",
                  "resumen_ejecutivo": "Un análisis exhaustivo, amplio y detailed de los hechos, las partes implicadas, los fundamentos jurídicos y la resolución final o pretensión.",
                  "puntos_criticos_o_riesgos": [
                    "Riesgo o punto crítico 1 con explicación detallada",
                    "Riesgo o punto crítico 2",
                    "Riesgo o punto crítico 3"
                  ],
                  "fechas_limite_importantes": [
                    "Plazo procesal 1 y fecha/días hábiles para responder",
                    "Plazo o fecha clave 2"
                  ],
                  "borrador_respuesta_preliminar": "Redacta un escrito o borrador formal completo y profesional para contestar o recurrir este documento."
                }
                """

                api_key = os.environ.get("OPENAI_API_KEY", "").strip()
                if not api_key:
                    raise ValueError("No se ha configurado la clave OPENAI_API_KEY en Render.")

                # Petición HTTP directa a la API de OpenAI
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
                    "tipo_documento": "Error en el análisis",
                    "resumen_ejecutivo": f"No se pudo completar el análisis. Detalle: {str(e)}",
                    "puntos_criticos_o_riesgos": ["Revisa el mensaje de error superior para ver la causa exacta."],
                    "fechas_limite_importantes": ["N/A"],
                    "borrador_respuesta_preliminar": "No disponible."
                }
                return render_template("resultado.html", data=error_data)

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
    
