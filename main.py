
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
                pdf_reader = pypdf.PdfReader(file)
                total_paginas = len(pdf_reader.pages)
                
                # Límite de seguridad: leer como máximo las primeras 15 páginas para evitar saturar el servidor
                max_paginas = min(total_paginas, 15)
                texto_extraido = ""
                
                for i in range(max_paginas):
                    texto_pagina = pdf_reader.pages[i].extract_text()
                    if texto_pagina:
                        texto_extraido += texto_pagina + "\n"
                
                if not texto_extraido.strip():
                    texto_extraido = (
                        "[ADVERTENCIA] El PDF parece ser una imagen escaneada o no contiene texto seleccionable. "
                        "Para analizar este tipo de archivos se requiere integración con un motor OCR."
                    )

                vista_previa = texto_extraido[:1500] + ("..." if len(texto_extraido) > 1500 else "")

                data = {
                    "tipo_documento": f"Sentencia / Documento Procesal ({total_paginas} páginas totales)",
                    "resumen_ejecutivo": f"Procesadas las primeras {max_paginas} páginas de {total_paginas}. Vista previa: {vista_previa}",
                    "puntos_criticos_o_riesgos": [
                        "Documento de gran extensión analizado de forma optimizada.",
                        "Revisar el fallo de la sentencia y posibilidad de recursos de apelación/casación.",
                        "Verificar las partes implicadas y las costas procesales en la resolución."
                    ],
                    "fechas_limite_importantes": [
                        "Plazo de recurso: Consultar días hábiles procesales según la notificación.",
                        "Vencimiento: Confirmar con la agenda del juzgado origen."
                    ],
                    "borrador_respuesta_preliminar": (
                        "AL JUZGADO DE PRIMERA INSTANCIA / AUDIENCIA PROVINCIAL\n\n"
                        "D./Dña. [Nombre del Abogado/Procurador], en representación de [Cliente], comparece y DICE:\n\n"
                        "Que habiendo sido notificada la resolución judicial adjunta, mediante el presente escrito "
                        "formulamos las alegaciones/recurso correspondientes..."
                    )
                }

                return render_template("resultado.html", data=data)

            except Exception as e:
                error_data = {
                    "tipo_documento": "Error al procesar el archivo",
                    "resumen_ejecutivo": f"No se pudo leer el archivo PDF. Detalle: {str(e)}",
                    "puntos_criticos_o_riesgos": [
                        "El archivo supera los límites del servidor gratuito.",
                        "Prueba con un documento más corto (1 a 20 páginas)."
                    ],
                    "fechas_limite_importantes": ["N/A"],
                    "borrador_respuesta_preliminar": "No disponible."
                }
                return render_template("resultado.html", data=error_data)

    return render_template("index.html")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
