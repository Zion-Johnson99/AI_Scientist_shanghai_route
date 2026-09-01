---
name: ppt-local
description: Edit existing PowerPoint files with a stable local workflow. Use when Codex needs to modify, translate, batch replace, normalize fonts, or extract editable text from .ppt or .pptx files that already exist on disk. Prefer this skill for existing deck maintenance, especially when text may live in text boxes, tables, or grouped shapes and the task benefits from python-pptx scanning before any visual review.
---

# PPT Local

Use this skill for existing PowerPoint maintenance. Keep `presentations` for generating new decks from scratch.

## Default Runtime

Always prefer this interpreter:

```text
D:\ProgramData\miniconda3\envs\Common\python.exe
```

Do not rely on bare `python` until the active shell is proven to resolve to the same path.

## Preflight

Run these checks in order before reading or writing a deck:

```powershell
D:\ProgramData\miniconda3\envs\Common\python.exe --version
D:\ProgramData\miniconda3\envs\Common\python.exe -m pip --version
D:\ProgramData\miniconda3\envs\Common\python.exe -c "from pptx import Presentation; print('ok')"
```

If the import check fails, stop and report the exact failure.

## Default Workflow

Follow this chain:

```text
preflight -> recursive scan -> editable object inventory -> confirm boundaries -> batch writeback -> font normalization -> targeted review
```

Use `python-pptx` as the default engine for text-oriented edits.

## Scan Scope

When scanning a deck, recursively inspect all editable text containers that `python-pptx` can reach:

- normal text boxes and placeholders
- table cells
- grouped shapes that contain text-capable children

Treat the scan result as the translation and replacement boundary. Produce an inventory before bulk edits when the task involves translation or large-scale replacement.

For each hit, capture enough context to avoid wrong replacements:

- slide index
- shape id when available
- shape type
- text snippet
- table row and column when applicable

## Translation And Replacement Rules

For translation, translate editable Chinese or source-language text that belongs to the requested scope.

Keep these items unchanged unless the user explicitly asks for them:

- URLs
- image-embedded text
- decorative raster content

If a slide contains both editable text and image text, translate only the editable text by default and call out the remaining image text clearly.

Before writing translated text back, confirm special boundaries such as:

- title-only slides
- slides where some Chinese text is part of an image
- links that should stay literal

## Writeback Rules

Do batch writeback only after the editable object inventory is complete.

After text replacement, normalize typography in the same pass when the task asks for consistent appearance:

- font family
- font size
- bold or regular weight
- paragraph alignment when explicitly requested

Preserve deck structure. Do not rebuild slides when a text edit is sufficient.

## Escalation To PowerPoint COM

Use PowerPoint COM only when one of these conditions appears:

- layout looks wrong after `python-pptx` writeback
- object coverage from `python-pptx` is incomplete
- final visual parity needs a second check

Treat COM as a supplemental review or repair path, not the default editor.

## Response Contract

When using this skill, report:

- interpreter path actually used
- preflight results
- scan scope that was covered
- excluded text classes such as URLs or image text
- whether COM review was needed

## Safety Notes

Prefer copying the source deck before destructive bulk edits when the user did not already ask to overwrite in place.

If the deck contains suspiciously empty scan results, stop and verify whether the visible text is inside images, SmartArt, charts, or unsupported embedded objects before claiming the deck has little editable content.
