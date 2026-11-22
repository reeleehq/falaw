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

| [`improvement`](#falaw.journal.improvement)(text, \*\*kw)   | Record an `improvement` entry in the default journal.   |
|------------------------------------------------------------------------------|---------------------------------------------------------|
| [`issue`](#falaw.journal.issue)(text, \*\*kw)         | Record an `issue` entry in the default journal.         |
| [`note`](#falaw.journal.note)(text, \*\*kw)          | Record a `note` entry in the default journal.           |
| [`recent`](#falaw.journal.recent)([n])                 | The last `n` entries, oldest first.                     |

### Classes

| [`Journal`](#falaw.journal.Journal)([directory])                               | File-backed append-only journal.                              |
|-----------------------------------------------------------------------------------------------------|---------------------------------------------------------------|
| [`JournalEntry`](#falaw.journal.JournalEntry)(\*, id, timestamp, kind, text[, ...]) | One journal record: a timestamped note, issue or improvement. |

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

#### append(, kind, text, tags=(), suggestion='', context=None)

Add an entry of `kind` with `text` to the journal and return it.

* **Return type:**
  [`JournalEntry`](#falaw.journal.JournalEntry)

#### filter(, kind=None, tag=None)

The entries matching the given `kind`, `tag` and other criteria.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`JournalEntry`](#falaw.journal.JournalEntry)]

#### recent(n=20)

The last `n` entries, oldest first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`JournalEntry`](#falaw.journal.JournalEntry)]

### *class* falaw.journal.JournalEntry(, id, timestamp, kind, text, tags=(), suggestion='', context=dict())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One journal record: a timestamped note, issue or improvement.

### falaw.journal.improvement(text, \*\*kw)

Record an `improvement` entry in the default journal.

* **Return type:**
  [`JournalEntry`](#falaw.journal.JournalEntry)

### falaw.journal.issue(text, \*\*kw)

Record an `issue` entry in the default journal.

* **Return type:**
  [`JournalEntry`](#falaw.journal.JournalEntry)

### falaw.journal.note(text, \*\*kw)

Record a `note` entry in the default journal.

* **Return type:**
  [`JournalEntry`](#falaw.journal.JournalEntry)

### falaw.journal.recent(n=20)

The last `n` entries, oldest first.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`JournalEntry`](#falaw.journal.JournalEntry)]
