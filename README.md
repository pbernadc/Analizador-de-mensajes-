# Analizador de Mensajes para el TFG

Este proyecto contiene un pequeño programa en Python que analiza mensajes de emergencias (por ejemplo, los de **ES-Alert** o los que circulan en redes sociales).  
El objetivo es ver si los mensajes son **claros, concisos, alarmistas o emotivos**, y más adelante añadir otras características (como autoridad, urgencia controlada, etc.).

---

## ¿Qué contiene este repositorio?

- `analizar_mensajes_basico.py` → el programa principal.  
- `.gitignore` → un archivo para que no se suban cosas que no hacen falta (como los Excels grandes o archivos temporales).

---

## ¿Cómo usar el programa?

1. Asegúrate de tener **Python 3.10 o superior** instalado en tu ordenador.  
   (Lo puedes descargar de [python.org](https://www.python.org/)).  

2. Instala las librerías necesarias. Abre una terminal en la carpeta del proyecto y escribe:
   ```bash
   pip install pandas openpyxl textstat emoji
