# Mein Test

A small offline-ready trainer for the [German naturalization test ("Einbürgerungstest")](https://www.bamf.de/SharedDocs/Anlagen/DE/Integration/Einbuergerung/gesamtfragenkatalog-lebenindeutschland.html?nn=282388). The data set is extracted directly from the official PDF and rendered via a lightweight web app that persists your progress locally in the browser and works offline once cached.

## Importing the question catalog

Install the Python dependency once (PyMuPDF), then run the importer with the supplied catalog:

```powershell
python -m pip install pymupdf
python scripts/import_pdf.py gesamtfragenkatalog-lebenindeutschland.pdf
```

The importer creates `data/questions.json` and stores question images under `data/images/`. Re-run it whenever the source PDF changes.

### Validating the import

After importing, you can validate that all questions have exactly 4 answers:

```powershell
python scripts/validate_answers.py
```

The validator checks:
- All 460 questions are present
- Each question has exactly 4 answers
- No answers have empty text

## Running the web app

Serve the project directory with a local web server so the browser can load the JSON:

```powershell
python -m http.server
```

Open `http://localhost:8000/` (or the published build at [https://gekkedev.github.io/mein-test/](https://gekkedev.github.io/mein-test/)) and start practicing. Your learned questions are saved in `localStorage`, so they persist between sessions on the same device.

## Install as an app (PWA)

1. Visit the app in your browser (e.g. `http://localhost:8000/` or [https://gekkedev.github.io/mein-test/](https://gekkedev.github.io/mein-test/)).
2. Wait for the splash screen to disappear—during this time the service worker caches the full question catalog and all images.
3. Use the browser’s install control ("Install app" in Chrome/Edge, "Add to Home Screen" on mobile Safari).

After installation you can launch the trainer from your desktop or home screen and it will run fully offline. When you refresh the page while online, the service worker re-validates `data/questions.json` and updates the offline cache automatically. If you change the code or asset list significantly, bump `CACHE_VERSION` in `sw.js` to force clients to pick up the new bundle.

## Credits & Licenses

- Iconography uses the bundled UnifrakturMaguntia typeface by J. Victor Gammel, licensed under the [SIL Open Font License 1.1](assets/fonts/OFL.txt).
- Development tooling relies on [Pillow](https://python-pillow.org) (Historical Permission Notice and Disclaimer license) for icon rendering and [PyMuPDF](https://pymupdf.readthedocs.io/) (GNU Affero General Public License v3) for parsing the official question catalog PDF.
