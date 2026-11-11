# DataPilot

Analítica aeronáutica de Gonzalo Muñoz García: briefing diario de noticias de aviación + dashboards interactivos de Power BI.

Web: https://gonzalomg-stack.github.io

## Estructura

```
index.html                      Página
assets/style.css                Diseño (modo claro + oscuro automático)
assets/app.js                   Lógica + CONFIG (enlace de Power BI)
assets/logo-mark*.png           Logo
data/news.json                  Noticias (lo regenera el bot)
scripts/fetch_news.py           Lector de feeds RSS → news.json
.github/workflows/update-news.yml  Ejecuta el script 2 veces al día
```

## Puesta en marcha (una sola vez)

1. En GitHub crea un repositorio público llamado **`gonzalomg-stack.github.io`** (exactamente así).
2. Pulsa **Add file → Upload files**, arrastra todo el contenido de esta carpeta (incluida la carpeta `.github`) y haz **Commit**.
   - Si el navegador no sube la carpeta oculta `.github`, créala a mano: **Add file → Create new file**, nombre `.github/workflows/update-news.yml` y pega el contenido.
3. **Settings → Pages** → Source: *Deploy from a branch* → Branch: `main` / `(root)` → Save.
4. **Settings → Actions → General** → *Workflow permissions* → **Read and write permissions** → Save.
5. **Actions → Update aviation news → Run workflow**. En ~1 minuto `data/news.json` se llena con noticias reales y la web se actualiza sola.

A partir de ahí, las noticias se actualizan a las 05:17 y 15:17 UTC cada día sin que hagas nada.

## Añadir el dashboard de Power BI

1. Power BI Service → abre el informe → **Archivo → Insertar informe → Publicar en la web (público)**.
2. Copia el **enlace** (`https://app.powerbi.com/view?r=...`), no hace falta el código iframe.
3. En `assets/app.js`, pega el enlace en `powerbiAtfmUrl: ""` y haz commit.

> "Publicar en la web" hace el informe público. Perfecto para datos abiertos de EUROCONTROL; no lo uses con datos privados.

## Cambiar las fuentes de noticias

Edita la lista `FEEDS` en `scripts/fetch_news.py`. Si un feed falla, se ignora y el resto sigue funcionando. Las categorías se asignan por palabras clave (`CATEGORIES`, mismo archivo).

## Probar en local

```
python scripts/fetch_news.py
python -m http.server 8000     # y abre http://localhost:8000
```
