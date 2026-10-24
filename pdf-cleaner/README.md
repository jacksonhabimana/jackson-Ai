# Jackson AI – PDF Book Cleaner

Edits any textbook PDF the way it was done for the REB Chemistry S4 book:

- removes named boxes/sections (Learning Activity, Key Unit Competence, …)
- removes parts that run to the end of a chapter (End of unit assessment)
- deletes pages (Foreword, References, …)
- removes old footers, closes all gaps, renumbers pages
- rebuilds the Table of Contents (clickable, + PDF bookmarks) with matching page numbers
- writes your own footer (e.g. your website) in bold black on every page

Text is removed exactly (PDF content-stream editing), so neighbouring text is never lost.

## Use it
Open `pdf-cleaner.html` on the site, choose a PDF, press **Use REB textbook settings** (or describe what to remove), then **Clean my book**.

## Deploy the server once (free) – Hugging Face Spaces
1. huggingface.co → New Space → SDK **Docker** → Blank → Public.
2. Upload everything in this `pdf-cleaner/` folder (Dockerfile, app.py, clean.py, analyze.py, reflow.py, cstream.py, requirements.txt) to the Space. It builds by itself (about 3 minutes).
3. Copy the Space address (for example `https://jackson-pdf-cleaner.hf.space`) and paste it in the page under **Server address**, or put it in `DEFAULT_SERVER` inside `pdf-cleaner.html`.

Render.com works the same way: New → Web Service → Docker, root directory `pdf-cleaner`.
Optional environment variables: `ALLOWED_ORIGINS` (default `https://jacksonhabimana.github.io`) and `MAX_UPLOAD_MB` (default 150).

## Local test
    pip install -r requirements.txt
    python clean.py book.pdf out.pdf --opts '{"remove_titles":["Learning Activity"],"footer_text":"https://jacksonhabimana.github.io/jackson-Ai/"}'
    uvicorn app:app --port 8000

## Known limits
- Boxes are found by their coloured background. Plain headings are removed down to the next heading of the same size (never more than 45 % of a page).
- A box whose leftover continues on the next page without its own title can stay behind, so check those pages.
- Chapter openers are recognised by a line such as `UNIT` or `CHAPTER` near the top. Set the word in the page if a book uses another one.
- Very large figures are never split, so a few pages may end with white space.
