import os
import json
import requests
from flask import Flask, render_template, request
import pypdf

app = Flask(__name__)

# --- FUNCIONES AUXILIARES PARA MAP-REDUCE ---

def call_openai_json(prompt_sistema, prompt_usuario, api_key):
    """Realiza una petición HTTP a GPT-4o esperando una respuesta JSON."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o",
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt_sistema},
            {"role": "user", "content": prompt_usuario}
        ],
        "temperature": 0.1
    }
    
    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=120)
    response_json = response.json()

    if response.status_code != 200:
        error_msg = response_json.get("error", {}).get("message", "Error desconocido en OpenAI")
        raise Exception(f"OpenAI API Error ({response.status_code}): {error_msg}")

    contenido = response_json["choices"][0]["message"]["content"]
    return json.loads(contenido)


def dividir_en_fragmentos(texto, max_caracteres=40000):
    """Divide un texto largo en fragmentos manejables respetando el contexto de la API."""
    fragmentos = []
    inicio = 0
    total = len(texto)
    
    while inicio < total:
        fin = min(inicio + max_caracteres, total)
        # Intentar no cortar a la mitad de una palabra o salto de línea si es posible
        if fin < total:
            ultimo_salto = texto.rfind('\n', inicio, fin)
            if ultimo_salto != -1 and ultimo_salto > inicio:
                fin = ultimo_salto
        fragmentos.append(texto[inicio:fin])
        inicio = fin
        
    return fragmentos


# --- RUTA PRINCIPAL ---

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

                # 1. Extracción completa del PDF
                pdf_reader = pypdf.PdfReader(file)
                total_paginas = len(pdf_reader.pages)
                
                texto_extraido = ""
                for i in range(total_paginas):
                    texto_pagina = pdf_reader.pages[i].extract_text()
                    if texto_pagina:
                        texto_extraido += f"\n--- PÁGINA {i+1} DE {total_paginas} ---\n" + texto_pagina
                
                if not texto_extraido.strip():
                    texto_extraido = "Documento escaneado sin texto digital reconocible."

                # 2. MAP-REDUCE LOGIC
                fragmentos = dividir_en_fragmentos(texto_extraido, max_caracteres=40000)
                
                # FASE MAP: Analizar cada fragmento individualmente
                resumenes_parciales = []
                prompt_map = """
                Analiza este fragmento de un documento. Extrae de forma sintética:
                1. Hechos, antecedentes, temas principales o argumentos presentados en este fragmento.
                2. Partes involucradas o nombres relevantes mencionados.
                3. Cláusulas, decisiones, fallos, obligaciones o datos clave.
                4. Fechas, plazos o importes económicos.
                
                Responde ÚNICAMENTE con JSON:
                {
                   "resumen_fragmento": "Resumen detallado de este tramo",
                   "datos_clave": ["Dato 1", "Dato 2"],
                   "fechas_o_plazos": ["Fecha/Plazo 1"]
                }
                """
                
                for idx, frag in enumerate(fragmentos):
                    es_ultimo = (idx == len(fragmentos) - 1)
                    etiqueta = "ÚLTIMO FRAGMENTO (CONTIENE LAS CONCLUSIONES/FALLO FINAL)" if es_ultimo else f"FRAGMENTO {idx+1} DE {len(fragmentos)}"
                    
                    user_prompt_map = f"[{etiqueta}]\n\n{frag}"
                    analisis_parcial = call_openai_json(prompt_map, user_prompt_map, api_key)
                    resumenes_parciales.append({
                        "posicion": etiqueta,
                        "es_final": es_ultimo,
                        "contenido": analisis_parcial
                    })

                # FASE REDUCE: Combinar todos los fragmentos en el formato final
                prompt_reduce = """
                Eres un Analizador Universal de Documentos impulsado por IA de nivel profesional multidisciplinar.
                Se te proporcionan los resúmenes analizados de TODOS los fragmentos de un documento extenso.

                INSTRUCCIÓN CRÍTICA PARA EL ANÁLISIS:
                - Presta ESPECIAL ATENCIÓN al ÚLTIMO FRAGMENTO, ya que ahí suelen encontrarse las conclusiones finales, las resoluciones procesales, el fallo de la sentencia, las firmas o el cierre del documento.
                - Garantiza que la resolución o fallo final figure de forma prominente en el resumen ejecutivo.

                Debes responder ÚNICAMENTE con un objeto JSON válido estructurado con las siguientes claves:
                {
                  "categoria_documento": "Categoría general (Ej: Legal/Judicial, Inmobiliario/Contratos, Financiero/Facturación, Recursos Humanos, Salud/Médico, Educación/Académico, etc.)",
                  "tipo_documento": "Nombre exacto del documento (Ej: Sentencia Penal, Contrato de Arrendamiento, Factura, Currículum Vitae, Apuntes de Examen, Temario Máster, Informe Clínico)",
                  "resumen_ejecutivo": "Un resumen exhaustivo, profundo y fluido adaptado a la naturaleza del documento. Explica contexto, partes involucradas, hechos probados, fundamentos y LA RESOLUCIÓN / FALLO / CONCLUSIÓN FINAL.",
                  "puntos_criticos_o_riesgos": [
                    "Punto crítico, fallo/condena final, cláusula de riesgo, requisito obligatorio o hallazgo principal 1",
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
                  "accion_o_borrador_recomendado": "Redacta una respuesta, correo, borrador procesal de recurso o contestación, contraoferta o recomendación formal según el contexto del documento."
                }

                REGLA ESTRICTA PARA 'preguntas_tipo_test':
                - SI Y SOLO SI el documento es de categoría EDUCACIÓN / ACADÉMICO (apuntes universitarios, libros de texto, máster, secundaria, temarios de oposición o guías de estudio), GENERA entre 3 y 5 preguntas tipo test para repaso.
                - PARA CUALQUIER OTRO TIPO DE DOCUMENTO (Contratos, Facturas, Nóminas, Sentencias, Currículums, Informes Médicos), DEBES DEJAR ESTE ARRAY COMPLETAMENTE VACÍO: "preguntas_tipo_test": []
                """

                user_prompt_reduce = f"Documento completo compuesto por {len(fragmentos)} fragmentos ({total_paginas} páginas en total).\n\nAnálisis acumulado de los fragmentos:\n{json.dumps(resumenes_parciales, ensure_ascii=False)}"

                data = call_openai_json(prompt_reduce, user_prompt_reduce, api_key)
                data["tipo_documento"] += f" ({total_paginas} páginas analizadas con Map-Reduce)"

                return render_template("resultado.html", data=data)

            except Exception as e:
                error_data = {
                    "categoria_documento": "Error",
                    "tipo_documento": "Error en el análisis",
                    "resumen_ejecutivo": f"No se pudo completar el análisis Map-Reduce. Detalle: {str(e)}",
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
