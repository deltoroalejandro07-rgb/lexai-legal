
import os
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
                # Leer el PDF
                pdf_reader = pypdf.PdfReader(file)
                texto_extraido = ""
                
                # Extraer texto página por página
                for page in pdf_reader.pages:
                    texto_pagina = page.extract_text()
                    if texto_pagina:
                        texto_extraido += texto_pagina + "\n"
                
                # Manejar el caso de PDFs escaneados o sin texto seleccionable
                if not texto_extraido.strip():
                    texto_extraido = (
                        "[ADVERTENCIA] El PDF parece ser una imagen escaneada o no contiene texto seleccionable. "
                        "Para analizar este tipo de archivos se requiere integración con un motor OCR (reconocimiento óptico)."
                    )

                # Limitar la vista previa para no saturar la pantalla si es muy extenso
                vista_previa = texto_extraido[:1500] + ("..." if len(texto_extraido) > 1500 else "")

                data = {
                    "tipo_documento": "Sentencia / Documento Procesal Extenso",
                    "resumen_ejecutivo": f"Texto procesado correctamente ({len(pdf_reader.pages)} páginas). Vista previa: {vista_previa}",
                    "puntos_criticos_o_riesgos": [
                        "Verificar la fecha de notificación oficial y notificación a las partes.",
                        "Revisar el fallo de la sentencia y posibilidad de recurso de apelación/casación.",
                        "Comprobar las costas procesales e importes fijados en la resolución."
                    ],
                    "fechas_limite_importantes": [
                        "Plazo de recurso: Revisar días hábiles aplicables según jurisdicción.",
                        "Vencimiento: Confirmar con la agenda del juzgado."
                    ],
                    "borrador_respuesta_preliminar": (
                        "AL JUZGADO DE PRIMERA INSTANCIA / AUDIENCIA PROVINCIAL\n\n"
                        "D./Dña. [Nombre del Abogado/Procurador], en representación de [Cliente], comparece y DICE:\n\n"
                        "Que habiendo sido notificada la resolución judicial adjunta, mediante el presente escrito "
                        "manifestamos la postura de esta parte conforme a Derecho..."
                    )
                }

                return render_template("resultado.html", data=data)

            except Exception as e:
                # Capturar cualquier error sin tumbar el servidor
                error_data = {
                    "tipo_documento": "Error al procesar el archivo",
                    "resumen_ejecutivo": f"No se pudo leer el archivo PDF. Detalle del error: {str(e)}",
                    "puntos_criticos_o_riesgos": [
                        "El archivo PDF podría estar protegido con contraseña.",
                        "El PDF podría estar dañado o tener un formato no compatible.",
                        "Prueba a subir un archivo PDF generado digitalmente."
                    ],
                    "fechas_limite_importantes": ["N/A"],
                    "borrador_respuesta_preliminar": "No disponible debido a un error de lectura."
                }
                return render_template("resultado.html", data=error_data)

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
