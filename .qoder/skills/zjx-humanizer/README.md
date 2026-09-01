# zjx-humanizer

`zjx-humanizer` adapts the public `blader/humanizer` skill into a daily chat and
technical collaboration style guide.

## Purpose

It removes AI-style templates from assistant replies and user-provided text while
preserving technical precision. It is intended for explanation, exchange, analysis,
debugging notes, code review feedback, research discussion, email drafts, and
documentation cleanup.

## Safety Review

Source reviewed: `https://github.com/blader/humanizer`

Local review directory: `/tmp/humanizer-review`

Observed files:

- `SKILL.md`
- `README.md`
- `WARP.md`
- `LICENSE`

Findings:

- No executable file was present in the downloaded repository.
- Top-level files were Markdown or plain text.
- Suspicious keyword hits came from install examples, documentation links, and writing
  examples.
- The original skill had no Bash, package manager, network, or shell execution tool.
- This adapted skill keeps only file-reading and file-editing tools.

## Trigger Scope

Use for:

- Daily chat.
- Explanation.
- Technical communication.
- Analysis.
- Debugging and troubleshooting explanations.
- Review comments.
- Research discussion.
- Text polishing.
- Email and documentation drafts.

Specialized skills still take priority for domain-specific work. This skill handles the
final communication layer.

## Version

- `1.0.0`: Initial ZJX adaptation from `blader/humanizer` 2.5.1.
