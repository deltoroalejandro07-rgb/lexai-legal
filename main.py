import os
import json
import re
import requests
from flask import Flask, render_template, request
import pypdf

app = Flask(__name__)

def anonimizar_texto_sensible(texto):
    if not isinstance(texto, str):
        return texto
    texto = re.sub(r'\b[XYZ]?\d{7,8}[A-Z]\b', '[DNI/NIE ANONIMIZADO]', texto)
    texto = re.sub(r'\b[A-Z]{2}\d{2}\s*(\d{4}\s*){4,5}\d{1,4}\b', '[IBAN ANONIMIZADO]', texto)
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

@app.route('/', methods=['GET', 'POST'])
def index():
    data = {}
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

            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                error = "Falta configurar la clave de OpenAI."
            else:
                target_preguntas = 100 if total_paginas > 100 else (15 if total_paginas > 5 else 8)
                prompt_sistema = f"Eres LexAI 2.0. ROL: {rol_usuario}. Genera JSON con 'categoria_documento', 'resumen_ejecutivo', 'puntos_criticos_con_riesgo', 'modulo_educacion' (con {target_preguntas} preguntas tipo test)."
                try:
                    payload = {"model": "gpt-4o", "messages": [{"role": "system", "content": prompt_sistema}, {"role": "user", "content": texto_extraído}], "response_format": {"type": "json_object"}}
                    response = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {api_key}"}, json=payload, timeout=60)
                    if response.status_code == 200:
                        data = json.loads(response.json()["choices"][0]["message"]["content"])
                        data["verificacion_exactitud"] = verificar_exactitud_datos(texto_extraído, data)
                        if "Financiero" in data.get("categoria_documento", ""):
                            descuadre = verificar_descuadre_financiero(texto_extraído)
                            if descuadre.get("hay_descuadre"):
                                data["puntos_criticos_con_riesgo"].append({"punto": descuadre["detalle"], "severidad": "Alto"})
                        if anonimizar:
                            data["resumen_ejecutivo"] = anonimizar_texto_sensible(data.get("resumen_ejecutivo", ""))
                        data["rol_analizado"] = rol_usuario
                    else:
                        error = "Error de API OpenAI."
                except Exception as e:
                    error = str(e)

    return render_template('resultado.html', data=data, error=error)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
