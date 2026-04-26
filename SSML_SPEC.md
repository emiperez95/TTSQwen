# TTSQwen SSML Spec

A minimal SSML-like markup. Plain text without any tags is rendered as-is in the request's default voice.

## Tags

### `<voice name="...">...</voice>` *(paired)*

Render the wrapped text in a different voice. `name` is either:

- a **preset speaker** (case-sensitive): `Aiden`, `Ryan`, `Vivian`, `Serena`, `Dylan`, `Eric`, `Uncle_Fu`, `Ono_Anna`, `Sohee`
- a **cloned voice** name (lowercase, matches a `voices/<name>.wav` file on the server)

Nesting is **not allowed**. Unknown names → HTTP 422. Text outside any `<voice>` block uses the request's default `voice`/`speaker` parameter.

### `<break time="500ms"/>` *(self-closing)*

Insert silence. Units: `ms` or `s`. Capped at 10 seconds.

### `<audio src="name"/>` *(self-closing)*

Insert a sound effect. `name` resolves to `server/sfx/<name>.wav`. List available names via `GET /api/sfx`.

### `<bg src="name" vol="0.15"/>` *(self-closing)*

Mix a background track under the **entire** output (looped). `vol` is `0.0`–`1.0`, default `0.15`. Only one `<bg>` per document — first one wins. **Disables low-latency streaming** (HLS and MP3-stream fall back to buffered audio).

## Rules and limits

- **Max 50 segments** per document (a segment = one speech run, one break, or one audio insert). Excess is truncated.
- **Auto-pauses**: if the input contains no SSML tags, the server auto-injects `<break time="300ms"/>` between sentences and `<break time="700ms"/>` between paragraphs (double newlines). If your script contains *any* SSML tag, auto-injection is skipped — add your own breaks.
- **Summarization**: any SSML in the input disables the summarizer. The script is rendered verbatim.
- **Max input length**: 10,000 characters.
- Tags are **case-insensitive** (the tag name itself; preset voice names are case-sensitive).
- Attribute values **must use double quotes**.
- `<voice>` and self-closing tags can be mixed; `<break>` and `<audio>` work inside or outside a `<voice>` block.

## Examples

### Plain podcast turn-taking

```xml
<voice name="Aiden">Welcome to the show. Today we're talking about voice synthesis.</voice>
<break time="400ms"/>
<voice name="Vivian">Thanks for having me — it's a topic I love.</voice>
```

### Break inside a turn, sound effect between turns

```xml
<voice name="Aiden">Let me set the scene. <break time="600ms"/> It's 1985, and computers can barely talk.</voice>
<audio src="record_scratch"/>
<voice name="Vivian">Wait — they couldn't talk at all back then?</voice>
```

### Background music under a whole episode

```xml
<bg src="lofi" vol="0.1"/>
<voice name="Aiden">Episode three. Let's get into it.</voice>
<voice name="Vivian">I've been waiting for this one.</voice>
```

### Mixing presets and clones (assumes `dolina.wav` exists on server)

```xml
<voice name="Aiden">Welcome back. Today's guest is Dolina.</voice>
<voice name="dolina">Glad to be here.</voice>
```

## How to call the API

`POST /speak` (buffered WAV), `/speak/stream` (chunked MP3), or `/speak/hls` (HLS playlist) — same body shape:

```json
{
  "text": "<voice name=\"Aiden\">Hello.</voice><break time=\"300ms\"/><voice name=\"Vivian\">Hi.</voice>",
  "summarize": false
}
```

`speaker`/`voice` at the top level become the **fallback** for any text outside a `<voice>` block. If every line is wrapped in `<voice>`, you can omit them.

Server: `http://10.18.1.2:9800`
