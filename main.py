import os
import json
import re
import io
import requests
from flask import Flask, render_template, request, make_response
import pypdf

app = Flask(__name__)

# --- FUNCIONES AUXILIARES ---

def anonimizar_texto_sensible(texto):
    if not isinstance(texto, str):
        return texto
    # Ocultar DNI/NIE
    texto = re.sub(r'\b[XYZ]?\d{7,8}[A-Z]\b', '[DNI/NIE ANONIMIZADO]', texto)
    # Ocultar IBAN
    texto = re.sub(r'\b[A-Z]{2}\d{2}\s*(\d{4}\s*){4,5}\d{1,4}\b', '[IBAN ANONIMIZADO]', texto)
    # Ocultar teléfonos
    texto = re.sub(r'\b(?:\+34|0034)?[679]\d{8}\b', '[TELÉFONO ANONIMIZADO]', texto)
    return texto

def verificar_exactitud_datos(texto_pdf, json_analisis):
    texto_limpio = " ".join(texto_pdf.lower().split())
    
    texto_a_verificar = json_analisis.get("resumen_ejecutivo", "") + " "
    for p in json_analisis.get("puntos_criticos_con_riesgo", []):
        texto_a_verificar += p.get("punto", "") + " "
        
    patron_cifras = r'\b(?:\d{1,3}(?:\.\d{3})+\d+|\d+)(?:,\d{1,2})?\s*(?:€|euros?|\$|USD|\%)\b'
    cifras_encontradas = re.findall(patron_cifras, texto_a_verificar, re.IGNORECASE)
    
    total_cifras = len(cifras_encontradas)
    cifras_validadas = 0
    alucinaciones_detectadas = []
    
    for cifra in cifras_encontradas:
        cifra_limpia = cifra.replace(" ", "").replace("€", "").replace("euros", "").replace("euro", "").strip()
        if cifra_limpia in texto_limpio.replace(" ", ""):
            cifras_validadas += 1
        else:
            alucinaciones_detectadas.append(cifra)
            
    return {
        "total_cifras_analizadas": total_cifras,
        "cifras_validadas": cifras_validadas,
        "hay_alucinacion": len(alucinaciones_detectadas) > 0,
        "cifras_no_encontradas": alucinaciones_detectadas
    }

def verificar_descuadre_financiero(texto_pdf):
    importes = re.findall(r'(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*(?:€|euros?)', texto_pdf, re.IGNORECASE)
    valores_numericos = []
    for imp in importes:
        try:
            val = float(imp.replace('.', '').replace(',', '.'))
            valores_numericos.append(val)
        except ValueError:
            pass
            
    if len(valores_numericos) >= 3:
        total_declarado = max(valores_numericos)
        suma_parcial = sum(valores_numericos) - total_declarado
        if abs(suma_parcial - total_declarado) > 1.0:
            return {"hay_descuadre": True, "detalle": f"Suma parcial ({suma_parcial}) difiere del total ({total_declarado})"}
            
    return {"hay_descuadre": False}

# --- RUTA PRINCIPAL ---

@app.route('/', methods=['GET', 'POST'])
def index():
    resultado_json = None
    texto_extraído = ""
    error = None
    total_paginas = 1
    rol_usuario = "Estudiante / Opositor"
    anonimizar = False

    if request.method == 'POST':
        rol_usuario = request.form.get('rol', 'Estudiante / Opositor')
        anonimizar = 'anonimizar' in request.form
        archivo = request.files.get('archivo')

        if archivo and archivo.filename != '':
            try:
                pdf_reader = pypdf.PdfReader(archivo)
                total_paginas = len(pdf_reader.pages)

                texto_extraído += f"=== INICIO DEL DOCUMENTO ===\n"
                for i in range(min(3, total_paginas)):
                    texto_extraído += f"--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "") + "\n"

                if total_paginas > 6:
                    texto_extraído += f"\n=== RESUMEN PÁGINAS INTERMEDIAS ===\n"
                    paso = max(1, total_paginas // 4)
                    for i in range(3, total_paginas - 3, paso):
                        texto_extraído += f"--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "") + "\n"

                texto_extraído += f"\n=== PARTE FINAL DEL DOCUMENTO ===\n"
                for i in range(max(0, total_paginas - 3), total_paginas):
                    texto_extraído += f"--- PÁGINA {i+1} ---\n" + (pdf_reader.pages[i].extract_text() or "") + "\n"

            except Exception as e:
                error = f"Error al leer el PDF: {str(e)}"

            if not texto_extraído.strip():
                texto_extraído = "Documento escaneado sin texto digital reconocible."

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                error = "Falta configurar la clave de OpenAI en el servidor."
            else:
                target_preguntas = 100 if total_paginas > 100 else (75 if total_paginas > 60 else (50 if total_paginas > 30 else (30 if total_paginas > 15 else (15 if total_paginas > 5 else 8))))

                prompt_sistema = f"""
                Eres LexAI Enterprise 2.0, auditor y tutor académico de precisión.
                Analizarás el documento considerando la posición o ROL DEL USUARIO: "{rol_usuario}".

                INSTRUCCIONES ESPECÍFICAS SEGÚN CATEGORÍA:

                1. CATEGORÍA "Educación/Académico" (Apuntes, libros, artículos, temarios):
                   - NO GENERAR RIESGOS NI CLÁUSULAS CRÍTICAS.
                   - Dejar "puntos_criticos_con_riesgo" VACÍO [].
                   - Genera dentro del objeto "modulo_educacion":
                     a) "resumen_esquematico": Una lista detallada donde cada apartado incluya OBLIGATORIAMENTE un resumen explicativo de 2 o 3 frases que desarrolle la teoría y los conceptos clave.
                     b) "glosario": 8 a 12 términos técnicos/clave con sus definiciones precisas.
                     c) "preguntas_tipo_test": Genera EXACTAMENTE {target_preguntas} preguntas tipo test representativas de todo el documento, con sus 4 opciones, respuesta correcta y explicación pedagógica detallada.

                2. OTRAS CATEGORÍAS (Inmobiliario, Financiero, Legal, Laboral):
                   - Evaluar cláusulas, leyes imperativas o descuadres numéricos en "puntos_criticos_con_riesgo".
                   - Dejar "modulo_educacion" con arrays vacíos.

                ESTRUCTURA DE RESPUESTA REQUERIDA (JSON VÁLIDO):
                {{
                "categoria_documento": "Educación/Académico | Inmobiliario/Contratos | Financiero/Facturación | Legal/Judicial",
                "tipo_documento": "Tipo exacto del archivo",
                "resumen_ejecutivo": "Introducción o visión general.",
                "puntos_criticos_con_riesgo": [
                    {{"punto": "Descripción del riesgo", "severidad": "Alto/Medio/Bajo"}}
                ],
                "modulo_educacion": {{
                    "resumen_esquematico": [ {{"titulo": "...", "resumen": "..."}} ],
                    "glosario": [ {{"termino": "...", "definicion": "..."}} ],
                    "preguntas_tipo_test": [ {{"pregunta": "...", "opciones": [], "respuesta_correcta": "...", "explicacion": "..."}} ]
                }}
                }}
                """

                try:
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json"
                    }
                    payload = {
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": prompt_sistema},
                            {"role": "user", "content": texto_extraído}
                        ],
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2
                    }

                    response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
                    
                    if response.status_code == 200:
                        contenido_ia = response.json()["choices"][0]["message"]["content"]
                        data = json.loads(contenido_ia)
                        
                        verificacion = verificar_exactitud_datos(texto_extraído, data)
                        data["verificacion_exactitud"] = verificacion

                        if "Financiero" in data.get("categoria_documento", ""):
                            descuadre = verificar_descuadre_financiero(texto_extraído)
                            if descuadre.get("hay_descuadre"):
                                data["puntos_criticos_con_riesgo"].append({
                                    "punto": descuadre["detalle"],
                                    "severidad": "Alto"
                                })

                        if anonimizar:
                            data["resumen_ejecutivo"] = anonimizar_texto_sensible(data.get("resumen_ejecutivo", ""))
                            data["tipo_documento"] = data.get("tipo_documento", "Documento") + f" ({total_paginas} págs. analizadas)"

                        data["rol_analizado"] = rol_usuario
                        resultado_json = data
                    else:
                        error = f"Error en la API de OpenAI: {response.text}"
                except Exception as e:
                    error = f"Error procesando la solicitud: {str(e)}"

    return render_template('resultado.html', resultado=resultado_json, error=error)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
