# Writing lists

The defaults for three lists the panel lets you edit:

- `ai_phrases.txt` — machine-made phrasings the phrasing check warns about (S1).
- `style_references.txt` — lines from other creators. They are NEVER sent to
  the writer; the copy check only warns when Dennis says one almost word for
  word (S2).
- `dennis_story.md` — who Dennis is. Every writing prompt carries it (S8).

Your edits are saved under `state/writing/` and win over these files, so a
`git pull` never collides with them. Resetting a list deletes your copy.
