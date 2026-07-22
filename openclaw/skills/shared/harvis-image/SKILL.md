---
name: harvis-image
description: >
  Analyze image files — EXIF metadata (dimensions, camera make/model,
  date taken, GPS) and visual content (description, OCR, objects,
  layout). Use whenever the user asks about a picture, screenshot,
  photo, or scanned document.
metadata:
  openclaw:
    emoji: "\U0001f5bc️"
    always: false
---

# Harvis Image — analyzing pictures, screenshots, photos

You **do** have the ability to analyze images. Never tell a user "I'm a
language model and can't see images" — that is wrong inside Harvis.
Two different paths cover the two kinds of questions users ask:

| User wants                                             | Use                                       |
|--------------------------------------------------------|-------------------------------------------|
| Dimensions, camera make/model, date taken, GPS, format, EXIF | `exec` with ImageMagick `identify`  |
| Description of what's in the picture, OCR, objects, text, layout, UI elements | `/api/tools/vision-query` (Kimi K2.5)  |
| Full structured document layout (PDF, DOCX, scanned pages) | `/api/tools/file-analyze` with a `file_id` |

If the user asks for both ("what is this photo of AND when was it
taken"), run both paths and combine. EXIF is nearly free; only call
the vision API when the question actually needs visual understanding.

## 1. Find the image

When a user uploads a file, Harvis prepends an `[Attached files from
the user]` block to your task message. It looks like:

```
[Attached files from the user]
1. IMG_2438.jpg — image/jpeg — url=https://cdn.discordapp.com/attachments/.../IMG_2438.jpg
2. receipt.pdf — application/pdf — file_id=550e8400-e29b-41d4-a716-446655440000

[Task]
When was this photo taken and what camera?
```

**Always read this block first.** If it's there, every attachment has
at least one of `url=`, `path=`, or `file_id=`. Handle in that order:

- **`url=`** — download it first with `curl`, then work on the local
  copy:
  ```
  bash -lc "curl -sSL -o /tmp/img.jpg 'THE_URL'"
  ```
  Pick the extension from the URL or Content-Type.
- **`path=`** — already on disk in a shared volume. Use directly.
- **`file_id=`** — for PDFs/DOCX go straight to
  `/api/tools/file-analyze` (§4). For images, first resolve to bytes
  if you need EXIF — usually there's also a URL you can use.

If no `[Attached files…]` block appears **and** no URL/path is in the
user's text, ask once: "No image attached — upload it or paste a
URL." Then stop. Do NOT say you're a text-only model.

## 2. EXIF / metadata — ImageMagick `identify`

Available in the OpenClaw container. Zero LLM cost.

**Do this in ONE call, not four.** When the user asks several
metadata questions about the same image ("dimensions AND camera
make AND model AND date taken"), they share one EXIF block. Run
`identify` once, parse the output, answer all fields. **Do NOT
spawn a sub-agent per field** — that's the classic mistake that
produces "please provide an image" on questions 3 and 4.

**Everything at once** (parseable pipe-delimited):
```
bash -lc "identify -format '%w|%h|%m|%[EXIF:DateTimeOriginal]|%[EXIF:Make]|%[EXIF:Model]|%[EXIF:GPSLatitude]|%[EXIF:GPSLongitude]' /tmp/img.jpg"
```

Fields, in order:
1. width (px)
2. height (px)
3. format (JPEG, PNG, HEIC, …)
4. DateTimeOriginal — when the photo was taken (may be `DateTimeDigitized` on some cams)
5. camera Make (Canon, Apple, Nikon, …)
6. camera Model (iPhone 15 Pro, EOS R5, …)
7. GPS latitude (if present)
8. GPS longitude (if present)

Empty fields mean the EXIF tag isn't set — normal for screenshots, edited
images, or stripped web images. Report them as "not available", don't
invent values.

**Dump the full EXIF block** (when you need something the format above
didn't cover):
```
bash -lc "identify -verbose /tmp/img.jpg | grep -E '^  (exif|Properties|Geometry|Format|Colorspace)' -i | head -80"
```

**Round a datetime down to the minute** (common ask):
```
bash -lc "date -d 'PARSED_DATETIME' '+%Y-%m-%d %H:%M'"
```
EXIF dates look like `2024:03:15 14:32:07` — replace the first two
colons with `-` before passing to `date`:
```
bash -lc "echo '2024:03:15 14:32:07' | sed 's|:|-|; s|:|-|' | xargs -I{} date -d '{}' '+%Y-%m-%d %H:%M'"
```

## 3. Visual content — `/api/tools/vision-query`

Use when the user wants to know *what's in* the image: description, OCR
(text inside), objects, UI layout, chart interpretation, receipts,
screenshots of code, etc.

Endpoint: `POST http://backend:8000/api/tools/vision-query`

```
bash --noprofile --norc +H -lc '
  B64=$(base64 -w0 /tmp/img.jpg);
  MIME=$(file --mime-type -b /tmp/img.jpg);
  curl -s -X POST http://backend:8000/api/tools/vision-query \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
    -H "X-OpenClaw-SessionKey: YOUR_SESSION_KEY" \
    -d "{\"image_b64\":\"$B64\",\"mime_type\":\"$MIME\",\"question\":\"YOUR QUESTION\"}"
'
```

Replace `YOUR_SESSION_KEY` with the exact session key from your Harvis
task message. Replace `YOUR QUESTION` with what the user actually asked
(or a specific instruction like "Transcribe all visible text. Return
plain UTF-8, one line per visual line."). The response JSON has
`{"analysis": "..."}`.

**Question-crafting tips:**

- For OCR: `"Transcribe all text visible in this image. Preserve line breaks. Return plain text only."`
- For objects: `"List every distinct object in this image with a one-word label."`
- For UI screenshots: `"What application is this? What is the visible state/screen? List clickable elements."`
- For chart/graph: `"Read this chart. Report: title, X axis, Y axis, all series, notable values."`
- For receipts/invoices: `"Extract: vendor, date, line items (name/qty/price), subtotal, tax, total. Return JSON."`

Keep the question specific — vague prompts produce vague answers, and
each call costs tokens on Moonshot.

**Size:** the endpoint downsizes anything over 1024px on the longest
side before calling Moonshot, so you don't need to pre-resize.

## 4. Full document layout — `/api/tools/file-analyze`

Only when you have a `file_id` (uploaded via Harvis UI/API) and the
user wants a structured breakdown of a multi-page doc (PDF, DOCX,
scanned pages). Returns JSON with section hierarchy + key points.

```
bash --noprofile --norc +H -lc '
  curl -s -X POST http://backend:8000/api/tools/file-analyze \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" \
    -H "X-OpenClaw-SessionKey: YOUR_SESSION_KEY" \
    -d "{\"file_id\":\"THE_UUID\",\"user_id\":USER_ID_INT,\"hint\":\"optional context\"}"
'
```

Parse the returned JSON. Do NOT forward the raw JSON to the user —
summarize or reformat per their question.

## 5. Reporting results

After you extract what the user asked for, report it directly and
concisely. Example for the "image creation time, dimensions, camera
make/model" ask:

> **Created:** 2024-03-15 14:32
> **Dimensions:** 4032x3024
> **Camera:** Apple iPhone 15 Pro

**Emit EXIF values as plain text. Do NOT wrap the value in
`**bold**` or `*italic*`.** Only the label gets bold. Wrong:
`**iPhone 5**` — you will sometimes corrupt this to `iPhone**`
when your output is truncated. Right: `Camera: Apple iPhone 5`
(or `**Camera:** Apple iPhone 5` — bold label only).

**Always return the full EXIF string verbatim.** If
`identify -format '%[EXIF:Model]'` prints `iPhone 5`, report
`iPhone 5` (both words). Never report just `iPhone` — that drops
the specific generation and is the exact failure the user will
flag. Same for Make: report `Apple`, not "the manufacturer is
Apple." Make + Model combined: `Apple iPhone 5` — preserve every
token the tool returned.

If a field is missing from EXIF, say so explicitly ("camera model not
in EXIF — likely a screenshot or re-encoded image"). Do not
make up values.

**NEVER fabricate metadata.** If `identify` prints an empty field, the
tag isn't in the file. Do not invent a date like "January 1, 2024"
because it "looks like a plausible screenshot timestamp." The only
sources of truth are:
  1. `identify` output (zero-cost, deterministic — use this first)
  2. `/api/tools/vision-query` (for what's *visually* inside the frame)

If neither path tells you a value, report it as "not available" and
stop. Hallucinating a timestamp or camera model is worse than saying
"not available" — it wastes the user's time and looks like you
cheated the task.

**Never end an image task with a pure acknowledgment.** `Copy that.`,
`Standing by.`, `On it.`, or `I'll analyze it` are not answers. For an
image task you must do one of:
1. run the image tools and report the extracted result, or
2. say you could not determine the answer confidently and name the exact
   blocker (for example: OCR returned nothing, EXIF missing, image too
   blurry, punch-card holes too ambiguous).

## Rules

- **Never** say "I don't have access to images." You do. Use the tools.
- **Never** try to guess a description from the filename. Call the
  vision endpoint.
- **Don't** base64-encode images over ~10 MB in one shot — downscale
  first with `convert -resize 1600x1600 in.jpg small.jpg` to keep the
  request body small.
- **Don't** leak the full base64 payload back to the user. They want
  the answer, not the pixel data.
- If `identify` or `curl` isn't installed (unusual — both are in the
  OpenClaw image), install via `apt-get install -y imagemagick curl`.
- For private/sensitive images, mention that the vision analysis runs
  on Moonshot (cloud) — user may want to redact or opt out.
