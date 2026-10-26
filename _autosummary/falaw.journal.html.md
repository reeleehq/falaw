# falaw.journal

Agent journal: append-only log of notes, issues and improvements.

Why this exists: agents (and falaw itself) leave traces here whenever
something is harder than expected, surprising, or worth remembering. The
Claude skill teaches future sessions to read recent entries before doing
novel work, so each session starts smarter than the last.

Usage:

```pycon
>>> from falaw import journal
>>> journal.note("schnell tier returns 1024x1024 by default")
>>> journal.issue("FLUX dev refused a benign prompt as NSFW",
...               suggestion="Try guidance_scale=2.0")
>>> journal.improvement("Add an `upscale_image` wrapper for clarity-upscaler",
...                     tags=("backlog",))
```

### Functions

| `improvement`(text, \*\*kw)   |    |
|-------------------------------|----|
| `issue`(text, \*\*kw)         |    |
| `note`(text, \*\*kw)          |    |
| `recent`([n])                 |    |

### Classes

| [`Journal`](#falaw.journal.Journal)([directory])                               | File-backed append-only journal.   |
|-----------------------------------------------------------------------------------------------------|------------------------------------|
| [`JournalEntry`](#falaw.journal.JournalEntry)(\*, id, timestamp, kind, text[, ...]) |                                    |

### *class* falaw.journal.Journal(directory=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

File-backed append-only journal.

Each entry becomes a single JSON file. Names are timestamp-prefixed, with
a process-wide sequence number breaking same-tick ties, so
`sorted(os.listdir(...))` yields insertion order without parsing.

```pycon
>>> import tempfile
>>> j = Journal(tempfile.mkdtemp())
>>> _ = j.append(kind="note", text="hello")
>>> _ = j.append(kind="issue", text="boom", suggestion="try X")
>>> [e.kind for e in j]
['note', 'issue']
```

### *class* falaw.journal.JournalEntry(, id, timestamp, kind, text, tags=(), suggestion='', context=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)
