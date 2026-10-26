# falaw.session

Session: optional stateful controller over a sequence of falaw operations.

Plain function calls work without a session. Sessions exist to make multi-step
flows ergonomic — a working directory, a result history, and a journal
binding that future-you (or another agent) can read.

### Classes

| [`Session`](#falaw.session.Session)([output_dir, journal, history])   | A working session for a sequence of falaw operations.   |
|--------------------------------------------------------------------------------------------|---------------------------------------------------------|

### *class* falaw.session.Session(output_dir=getcwd(), journal=\_default_journal(), history=list())

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A working session for a sequence of falaw operations.

```pycon
>>> import tempfile
>>> s = Session(output_dir=tempfile.mkdtemp())
>>> s.history
[]
```
