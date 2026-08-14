Python


import os
import json
from flask import Flask, render_template, request, flash, redirect
from pypdf import PdfReader
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "clave_secreta_lexai_2026")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def extraer_texto_pdf(stream):
    try:
        reader = PdfReader(stream)
        texto = ""
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texto += t + "\n"
        return texto.strip()
    except Exception as e:
        return None

def analizar_texto_legal(texto_documento):
    prompt_sistema = """
    Eres un abogado senior experto en derecho procesal y civil. 
    Analiza el documento legal adjunto y responde strictly en formato JSON válido:
    {
      "tipo_documento": "Tipo de documento detectado",
      "resumen_ejecutivo": "Resumen ejecutivo claro de 3 frases.",
      "puntos_criticos_o_riesgos": ["Riesgo 1 o cláusula abusiva", "Riesgo 2"],
      "fechas_limite_importantes": ["Fecha límite 1", "Fecha límite 2"],
      "estrategia_sugerida": "Recomendación técnica procesal.",
      "borrador_respuesta_preliminar": "Texto formal de respuesta o alegación."
    }
    """
    try:
        respuesta = client.chat.completions.create(
            model="gpt-4o",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": f"Analiza el siguiente texto legal:\n\n{texto_documento}"}
            ],
            temperature=0.15
        )
        return json.loads(respuesta.choices[0].message.content)
    except Exception as e:
        return {"error": "Error al procesar con IA", "detalles": str(e)}

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        if 'file' not in request.files:
            flash("No se ha seleccionado archivo")
            return redirect(request.url)
        file = request.files['file']
        if file and file.filename.lower().endswith('.pdf'):
            texto = extraer_texto_pdf(file.stream)
            if not texto:
                flash("PDF vacío o no legible")
                return redirect(request.url)
            analisis = analizar_texto_legal(texto)
            return render_template("resultado.html", data=analisis)
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
