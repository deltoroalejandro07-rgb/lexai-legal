import os
import json
import requests
from flask import Flask, render_template, request
import pypdf

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def index():
    data = {}
    error = None

    if request.method == 'POST':
        rol_usuario = request.form.get('rol', 'Neutro')
        archivo = request.files.get('archivo')

        if not archivo or archivo.filename == '':
            error = "Por favor, selecciona un archivo PDF válido."
        else:
            try:
                pdf_reader = pypdf.PdfReader(archivo)
                total_paginas = len(pdf_reader.pages)
                texto_extraído = ""
                for i in range(min(total_paginas, 10)):
                    texto_extraído += f"--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "") + "\n"
            except Exception as e:
                error = f"Error al leer el archivo PDF: {str(e)}"

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                error = "Falta configurar la clave OPENAI_API_KEY en las variables de entorno de Render."
            elif not error:
                prompt_sistema = (
                    f"Eres LexAI 2.0. ROL: {rol_usuario}. Analiza el documento y responde estrictamente "
                    f"en formato JSON válido con estas claves exactas: "
                    f"'categoria_documento' (string), "
                    f"'resumen_ejecutivo' (string), "
                    f"'puntos_criticos_con_riesgo' (lista de strings), "
                    f"'esquema_detallado' (lista de objetos con 'titulo' y 'resumen_seccion'), "
                    f"'modulo_educacion' (lista de objetos con 'pregunta', 'opciones' como lista de 4 strings, y 'respuesta_correcta')."
                )
                try:
                    payload = {
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": prompt_sistema}, 
                            {"role": "user", "content": texto_extraído}
                        ],
                        "response_format": {"type": "json_object"}
                    }
                    response = requests.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}"},
                        json=payload,
                        timeout=60
                    )
                    if response.status_code == 200:
                        contenido = response.json()["choices"][0]["message"]["content"]
                        data = json.loads(contenido)
                        data["rol_analizado"] = rol_usuario
                    else:
                        error = f"Error de OpenAI ({response.status_code}): {response.text}"
                except Exception as e:
                    error = f"Error al procesar la respuesta de la IA: {str(e)}"

    return render_template('resultado.html', data=data, error=error)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
