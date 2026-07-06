# Voice Profile

## Source
Derived from sentence-level analysis of multiple published papers across systems and ML venues.

---

## Sentence-Level Style

### Length
- Mean words/sentence in final versions: ~21
- Student drafts average ~24 words/sentence — the advisor compresses by ~12%
- Maximum sentence length in final versions: ~40 words (for contribution-list items)
- Shortest functional unit: single-clause Takeaway sentences

### Structure
- **Claim-first**: Topic sentences lead with the assertion, followed by evidence. State the claim before citing the table or figure.
- **Parallel construction in contribution lists**: "(1) Learning problem. We formulate... (2) Design. We implement... (3) Evaluation. We demonstrate..."
- **Rhetorical questions** (sparingly, in introductions only): "Do speed tests need to transmit their full data volume to produce accurate results?"
- **Colon elaboration**: "Three fundamental limitations: (i) non-stationarity... (ii) no tuning knob... (iii) inability to incorporate..."

### Voice markers
- Avoids first-person hedging: rarely "We believe" or "We think" — prefers "We show" or "This confirms"
- Zero exclamation marks in final versions
- Minimal use of "However" as a paragraph opener (used for gap transitions, never as filler)
- Active voice everywhere — no exceptions. "System X achieves" not "accuracy was achieved by System X." "We evaluate on dataset X" not "Experiments were conducted on dataset X." "We collected data from campus gateway" not "Data was collected from campus gateway." Passive voice is never the right choice — it obscures agency and weakens prose.

---

## Paragraph Density

### Sentences per paragraph
- Introduction labeled blocks: 3–6 sentences (tight, focused)
- Design sections: 4–8 sentences (mechanism explanations need space)
- Evaluation result paragraphs: 3–5 sentences before a Takeaway
- Takeaway paragraphs: 1–3 sentences (maximally compressed)

### Information density
- No empty "connector" paragraphs — every paragraph either (a) makes a claim, (b) presents evidence, or (c) synthesizes a takeaway
- **Signposting through claims, not placeholders.** Sections may open with a preamble that states the section's conclusion or purpose — "This section shows that event-centric decomposition reduces error 13× by analyzing three failure modes." What is banned is *content-free* preambles — "In this section, we describe our evaluation setup" — which delay the claim without guiding the reader. The test: does the opening sentence tell a skim-reader what the section *concludes*, or only what it *contains*?
- Quantitative data density in evaluation: one number per clause, pattern per paragraph, takeaway per experiment cluster

---

## Tone

### Assertive vs. hedged
- **Final versions are strongly assertive**: "System X achieves 2–4× higher savings" not "System X appears to offer improved savings"
- **Hedging reserved for scope limitations**: "Our evaluation focuses on dataset Y" (scoping, not undermining)
- **Calibrated confidence**: Claims match evidence scope. No "we solve the problem of" — instead "we address [specific aspect] of [bounded problem]"
- Measured academic register in ML venues: slightly less assertive than systems venues

### Tonal evolution from student draft to final
| Dimension | Student draft | Final version |
|-----------|-------------|---------------|
| Enthusiasm | "shown immense promise" | "is transforming" |
| Hedging | "can potentially offer" | "achieves" |
| Scope | "universal solution" | "methodology-agnostic layer" |
| Agency | "we propose" | "this paper does not focus on X; instead it addresses Y" |

---

## Vocabulary Patterns

### Preferred terms
- Infrastructure language: "layer", "substrate", "abstraction"
- Analysis-of-structure language: "disaggregation", "decomposition"
- Prioritization language: "first-order requirement"
- Design-parameter language: "configurable trade-off"
- Formal precision: "intrinsic evaluation"

### Avoided terms (consistently removed in editing)
- "novel" — never in final versions
- "significant" / "substantial" / "impressive" / "promising" — replaced with numbers
- "state-of-the-art" — used only when naming a specific prior system
- "paradigm" / "leverage" / "utilize" — academic filler
- "In this paper, we..." — always removed

### Named abstraction coining pattern
- The advisor typically coins 1–2 named abstractions per paper
- Naming convention: compound noun phrase with architectural metaphor (e.g., "external termination layer," "progressive disaggregation," "intrinsic evaluation framework")
- Named abstractions appear ONLY in final versions — they are discovered through writing, not pre-planned

---

## AI-Rhetoric Avoidance

LLM-generated prose carries identifiable stylistic signatures that distinguish it from polished human academic writing. Final versions remove these signatures. The style audit applies to every draft, every time.

### No em-dashes

Em-dashes (`—` in Unicode, `---` in LaTeX) are a strong AI-writing signature. Remove systematically and replace by punctuation appropriate to the context:

- **Parenthetical insertion** (`X — clause — Y`): use parentheses (`X (clause) Y`) for short interjections, or commas (`X, clause, Y`) for longer asides.
- **List clarification** (`X — list of items`): use a colon (`X: list of items`) or rephrase with `namely` or `for instance`.
- **Amplifying clause** (`X — amplification`): split into two sentences (`X. Amplification.`) or use a colon.
- **Soft contrast** (`X — but Y`): use a comma plus conjunction, or a sentence break.
- **Part / section headings** (`Part I — Foundations`): use a colon (`Part I: Foundations`).
- **Author lines** (`Author — Affiliation`): use a comma.

The one exception: em-dashes inside direct quotations from external sources, where preserving the original punctuation matters for fidelity. Quoted source material aside, no em-dashes anywhere.

### No negation as rhetoric

Negation used as a stylistic move (elevation, contrast, definition by absence) is an AI tell. Negation used to state a real factual absence is acceptable. The test before keeping a negation: would the sentence lose factual content if the negation were removed and rewritten positively? If yes, the negation is doing factual work and stays. If no, the negation was rhetorical and must go.

**Rhetorical negations to remove:**

| Pattern | Example | Positive rewrite |
|---|---|---|
| `not only X; it Y` (fake stake-raise) | "The framework's pedagogical value is not only claimed; it has been measured." | "Student survey data supports the framework's pedagogical claim." |
| `X, not Y, is what Z` (definition by exclusion) | "Cross-layer loop coupling, not any single binding constraint, is what makes satellite-network design hard." | "Cross-layer loop coupling makes satellite-network design hard." |
| `not X but Y` (false contrast) | "Driven not by architectural elegance but by the cost of operating licensed spectrum at scale." | "Driven by the cost of operating licensed spectrum at scale." |
| `X is what Y does not satisfy` (definition by absence) | "That structural check is what AI plausibility does not satisfy." | "AI plausibility fails this structural check." |
| `wider than X alone` / `more than just X` (soft elevation) | "The audience is wider than the textbook market alone." | "The book has two distinct audiences." |
| `is not in competition with X` (soft framing) | "The book is not in competition with them as references." | "The book complements them as references." |
| `treat X as Y rather than as Z` (contrast via negation) | "They treat protocol history as background rather than as evidence." | "This book treats protocol history as evidence of recurring structural problems." |

**Factual negations to keep:**

- `"Students cannot derive..."` — describes a real capability gap that motivates the claim.
- `"39 of whom had taken..."` — quantitative fact.
- `"The system fails when..."` — describes a real failure mode.
- `"share the same signal but cannot see each other"` — describes a structural coupling problem.

### Other AI tells to scan for

- **Filler intensifiers**: `real`, `truly`, `genuinely`, `in fact`, `indeed`, `actually` (when used for emphasis rather than to disambiguate). Delete.
- **Connective tissue**: `in turn`, `crucially`, `notably`, `importantly`, `it is worth noting`, `that said`. Delete unless doing structural signposting work that is otherwise absent.
- **Stake-raising adverbs**: `precisely because`, `exactly`, `specifically` (when used for emphasis rather than precision). Delete or replace with the precise referent.
- **Promotional closers**: `a concrete demonstration of X`, `the kind of Y that...`, `a testament to Z`. Replace with the fact alone.
- **Hyper-triadic structure**: three-item lists where two would suffice, repeated `X does A, B, and C` patterns three sentences in a row. Vary structure or compress.
- **Hyper-balanced contrasts**: `on one hand... on the other hand...` when only one side is being made. Drop the false symmetry.
- **Definitional metaphors**: `at its heart`, `at its core`, `in essence`, `fundamentally`. Replace with the actual claim.
- **"X meets Y" framings**: `where structure meets scale`, `where theory meets practice`. Concrete claim instead.

The audit pass for these tells happens after content is settled and before any draft is shared. Every flagged construction must either be replaced with a direct positive alternative or justified by a specific factual requirement.

---

## Structural Preferences

### Labeled paragraphs (systems venues)
- Labels are short imperative phrases: "The opportunity.", "Key contributions.", "Limitations of existing approaches."
- Each label is a narrative contract — what follows must deliver on the label
- Removed for ML venues — replaced with colon-style subtitles

### Heading style
- **Systems venues**: Problem-driven. "Why do linear approaches fail?" / "Taming the tails"
- **ML venues**: Method-driven. "Embedding Analysis: quantifying representation space utilization"
- **Universal**: Claim-first in final versions. Never "Section 4" or "Evaluation Results" — always a claim or question

### Heading mechanics (capitalization, length, terminal punctuation)

These rules apply uniformly across `\chapter{}`, `\section{}`, `\subsection{}`, `\subsubsection{}` titles. They are non-negotiable in final versions because reviewers and committee members read the table of contents first; inconsistent heading mechanics signal a paper that hasn't been polished.

- **Capitalization: pick one style and apply it everywhere.** Either Title Case ("Background and Related Work") or sentence case ("Background and related work") — the choice depends on the venue's convention, but mixing the two within a single document is a hard error. The most common failure mode is keeping the original paper's heading style intact when assembling a dissertation or extended version: chapter A uses Title Case (its CCS paper), chapter B uses sentence case (its NeurIPS paper), and the reader gets visual whiplash. The fix is mechanical: pick the dominant style and rewrite the outliers.
- **Length: aim for a single typeset line.** Headings that wrap to two lines fragment the visual hierarchy and read as unfinished. The hard test: paste each heading into the target template at the right level and confirm it fits on one line at the rendered width. If a heading wraps, compress before submitting — there is almost always a wordier draft of the same claim. Wrapping is acceptable only when the heading carries a numbered claim that cannot be shortened without losing precision (e.g., "Event-centric decomposition reduces tail error 13× across four workloads"). Generic descriptive headings that wrap ("Comparison of BatchNorm layer, decorrelation, and whitening") never earn the wrap.
- **No terminal punctuation on section/subsection titles.** `\section{Compute resources.}` is wrong; the period belongs only at the end of `\smartparagraph{}` labels and bolded run-in paragraph labels. Sectioning commands are typeset as headings, not as sentences.
- **Compression discipline.** Long headings are almost always under-compressed claims. "Comparison of BatchNorm layer, decorrelation, and whitening" → "Decorrelation alternatives". "Causal Sensitivity Testing: interventional analysis of protocol and context dependencies" → "Causal Sensitivity Testing" (the subtitle restates the section's own content). The compression operations from `compression_patterns.md` apply to headings: remove subordinate clauses, replace generic adjectives with specific terms or delete, fold redundant glosses into the body text where they belong.

### Contribution framing
- Numbered, labeled list: "(1) Learning problem. (2) Design. (3) Evaluation."
- Each item starts with a bold domain label, followed by a claim (not a process description)
- "We show" preferred over "We propose" — positions the paper as delivering evidence, not promises

---

## Engineering Specificity

- Named protocols and tools, not generic references (not "network metrics" but "RTT, retransmissions, congestion window")
- Named data sources, not generic references (not "speed tests" but the specific benchmark names)
- Named scales: "2–4×", "65% compression" (not "significantly reduced")
- Architecture as metaphor: "layer" = pluggable component; "substrate" = foundational platform; "framework" = evaluation methodology

---

## Storytelling register (Arpit, discourse-led) — added 2026-06-30

Derived from Arpit's own reconciliation of a co-author's edits on the SIGCSE Pramana intro (see
`reflections/arpit_storytelling_deconstruction_2026-06-30.md`). This register REFINES the base for
Arpit's papers: keep the base's claim-first, hedging-light, named-over-vague bones, but allow a more
guided, signposted surface. Two layers.

### Layer A — storytelling moves (these RELAX or override specific base rules)
1. **Discourse markers are narrative glue, not filler.** Keep sentence-opening signposts that mark the
   argument's move: "However,", "More concretely,", "The catch is,", "Interestingly,", "Here,",
   "What's worth noting is that". This RELAXES the AI-tell ban on "notably/crucially" — strip a marker
   only when it precedes no actual logical move (pure throat-clearing).
2. **Name the thesis once as an explicit, quotable sentence that echoes the title** (e.g., "This
   pedagogical transformation from teaching 'how networks work' to 'why they work' requires
   facilitating experiential learning"). Do not leave the thesis only implied.
3. **Direct research-statement framing**: "This paper explores / shows / argues…" — prefer it over
   indirect narrative devices ("Suppose, instead…").
4. **Use i.e./e.g. parentheticals freely** to gloss a term in the reader's words (i.e.) or name
   concrete instances (e.g.), inline.
5. **Deliberate repetition of the central title concept across beats is cohesion, not redundancy.**
   The de-dup instinct does not apply to the load-bearing thesis term.
6. **Explanatory length and a sparing emphasis word are fine.** Longer discursive sentences are OK in
   this register; a single "truly"-type intensifier marking the stakes is permitted (NOT auto-banned).
7. **Formatting: one sentence per source line** in the .tex when editing Arpit's papers (easier diffs).

### Layer B — precision class (apply paper-wide as a sweep, not per-edit)
A domain-expert co-author (Walter) caught these; our process missed them because we scoped existing
rules too narrowly. Run each as a PAPER-WIDE scan:
8. **Hedge scan.** Flag every empirical/causal universal ("X takes/means/is Y"); ask "always, or
   can/typically/often?" Add the calibrated hedge.
9. **Referent scan.** Flag every vague "it / this / these / that <noun>" and vague subject
   ("a subset / some / you / a second / two"); name the antecedent or actor.
10. **Conflation scan.** Disambiguate thing-vs-process ("generating the data", not "the data") and
    abstract-vs-concrete ("cost = student time").
11. **Explicitness scan.** Prefer explicit numbers and named actors ("about 20%", "a host",
    "respondents") over folksy approximations ("a sixth", "you").

### Process rules (why we missed Layer B)
- **Generalize a flag into a class.** When one instance is flagged (by a reviewer or by Codex), treat
  it as representative and grep the whole paper for siblings — do not point-fix.
- **Adopt once → sweep everywhere.** When a clarification is accepted (e.g., cost = time), apply it at
  every occurrence of the concept before moving on.
- **An LLM reviewer (Codex) does NOT substitute for a domain-expert human pass** on the precision
  class; over-assertion, vague referents, and conflation are collective LLM blind spots.
- **Author-specific style is not self-enforcing across collaborators.** Re-apply Arpit's hard rules
  (e.g., no em-dashes) after any co-author edit pass.
