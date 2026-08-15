
import os
import json
from flask import Flask, render_template, request
import pypdf
from openai import OpenAI

app = Flask(__name__)

# Conectar con OpenAI usando la clave guardada en Render
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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

                # Instrucciones estrictas para la IA
                prompt_sistema = """
                Eres un abogado senior experto. Analiza el documento procesal/legal y responde ÚNICAMENTE con un objeto JSON válido con este formato:
                {
                  "tipo_documento": "Tipo exacto de documento (Ej: Sentencia Penal, Notificación de Embargo, Contrato de Arrendamiento)",
                  "resumen_ejecutivo": "Un análisis exhaustivo, amplio y detallado de los hechos, las partes implicadas, los fundamentos jurídicos y la resolución final o pretensión.",
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

                # Llamada a GPT-4o
                response = client.chat.completions.create(
                    model="gpt-4o",
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": prompt_sistema},
                        {"role": "user", "content": f"Documento a analizar ({total_paginas} páginas totales):\n\n{texto_extraido[:14000]}"}
                    ],
                    temperature=0.2
                )

                data = json.loads(response.choices[0].message.content)

                if total_paginas > 15:
                    data["tipo_documento"] += f" ({total_paginas} págs. - Primeras 15 analizadas)"

                return render_template("resultado.html", data=data)

            except Exception as e:
                error_data = {
                    "tipo_documento": "Error de conexión con la IA",
                    "resumen_ejecutivo": f"No se pudo completar el análisis con la IA. Detalle: {str(e)}",
                    "puntos_criticos_o_riesgos": ["Verifica que la variable OPENAI_API_KEY esté bien puesta en Render y que tu cuenta tenga saldo."],
                    "fechas_limite_importantes": ["N/A"],
                    "borrador_respuesta_preliminar": "No disponible."
                }
                return render_template("resultado.html", data=error_data)

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
