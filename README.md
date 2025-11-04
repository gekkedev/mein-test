# Mein Test

A small offline-ready trainer for the [German naturalization test ("Einbürgerungstest")](https://www.bamf.de/SharedDocs/Anlagen/DE/Integration/Einbuergerung/gesamtfragenkatalog-lebenindeutschland.html?nn=282388). The data set is extracted directly from the official PDF and rendered via a lightweight web app that persists your progress in the browser.

## Importing the question catalog

Install the Python dependency once (PyMuPDF), then run the importer with the supplied catalog:

```powershell
python -m pip install pymupdf
python scripts/import_pdf.py gesamtfragenkatalog-lebenindeutschland.pdf
```

The importer creates `data/questions.json` and stores question images under `data/images/`. Re-run it whenever the source PDF changes.

## Running the web app

Serve the project directory with a local web server so the browser can load the JSON:

```powershell
python -m http.server
```

Open `http://localhost:8000/` and start practicing. Your learned questions are saved in `localStorage`, so they persist between sessions on the same device.
