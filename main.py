
import os
from flask import Flask, render_template, request, flash, redirect
from pypdf import PdfReader

app = Flask(__name__)
app.secret_key = "clave_secreta_lexai_2026"

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
    resumen = texto_documento[:300] + "..." if len(texto_documento) > 300 else texto_documento
    return {
      "tipo_documento": "Documento Legal Procesal (Analizado)",
      "resumen_ejecutivo": f"Se ha extraído y procesado el texto del archivo correctamente. Vista previa: {resumen}",
      "puntos_criticos_o_riesgos": [
          "Verificar la fecha de notificación oficial.",
          "Revisar competencia territorial del juzgado originario.",
          "Comprobar firmas digitalizadas en el anexo."
      ],
      "fechas_limite_importantes": [
          "Plazo de alegaciones: 10 días hábiles desde la recepción.",
          "Vencimiento sugerido: Revisar calendario procesal."
      ],
      "borrador_respuesta_preliminar": "AL JUZGADO DE PRIMERA INSTANCIA\n\nD./Dña. [Nombre del Procurador/Abogado], en representación de [Cliente], comparece y como mejor proceda en Derecho, DICE:\n\nQue habiendo sido notificado el presente documento, formulamos contestación en tiempo y forma..."
    }

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
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
