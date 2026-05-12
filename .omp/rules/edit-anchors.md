---
description: Guidance for using Oh My Pi's hashline edit anchors correctly
alwaysApply: true
---

# Edit Anchor Usage

Oh My Pi uses a **hashline** edit system. Every line in tool output is prefixed with an anchor like `5th|` or `42ab|`. These anchors are how you target edits — not line numbers, not content text. Copy anchors **exactly** from the most recent `read` output.

## Anatomy of an anchor

```
41th|def alpha():
 ^^^ ^
 line hash
```

The anchor is `41th`, not the content after `|`. The hash is content-fingerprinted — re-reading after changes produces new anchors.

## Choose the smallest op

| Op | When |
|----|------|
| `+ ANCHOR ~content` | Adding lines after a line |
| `< ANCHOR ~content` | Adding lines before a line |
| `- A..B` | Deleting lines |
| `= A..B ~content` | Replacing content |

Rules of thumb:
- Pure addition → `+` or `<`, never `=`
- Pure deletion → `-`, never `=`
- `= A..B` is ONLY for when lines inside A..B are actually being changed. If you `= A..B` and the payload is identical to what was there minus one line, you have the wrong op — use `-` plus a narrow `+`/`<` instead.

## Read sections, not snippets

Tool output shows bounded context around matches. Always read a wider range around the target before editing. A `read` with `:50-100` shows the anchors for every line. If anchors look stale (from a different file state), re-read.

## Do not copy anchors from stale output

Every edit invalidates anchors for the affected file. After an edit is applied, the file is in a new state. The next `read` produces fresh anchors. Using old anchors on a changed file is the single most common failure mode.

## Recognise when anchors are stale

If you try an edit and the tool reports the anchor line is gone or doesn't match, the file has changed. Re-read the file (or at least the affected section) to get fresh anchors before retrying.

## Common traps

1. **Wrong anchor**: You pasted an anchor from one file into an edit for another file. Verify file paths.
2. **Missing `~`**: Every payload line inside an edit MUST start with `~`. A bare line (no leading `~`) is invalid syntax.
3. **Using `= A..B` when a `+` would do**: If you're adding one line at a boundary, use `+`. A `= A..B` that reproduces all existing lines unchanged is wrong.
4. **Widening `= A..B` beyond a syntactic boundary**: If deleting lines A through B would split an unclosed bracket, paren, or string, widen the range to a self-contained boundary, or use `+`/`-` instead.
5. **Implicit `BOF`/`EOF` names**: These work for `<`/`+` — `< BOF` and `+ BOF` both prepend; `< EOF` and `+ EOF` both append. 

## Before submitting an edit

- Is every anchor from the latest `read` of that file?
- Is every payload line prefixed with `~`?
- Is the op the smallest one that does the job?
- If replacing content, does every line in the `~` payload differ from what was there? If any line is unchanged, the range is too wide.
