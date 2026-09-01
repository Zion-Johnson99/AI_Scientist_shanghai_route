# Kurose Voice Profile

A textbook-prose voice profile that complements `voice_profile.md`. Use this when the user explicitly asks for "Kurose voice," "Kurose pass," or warmth/rhythm appropriate to a Kurose-Ross style textbook. Derived iteratively from Arpit Gupta's project-description audits (book pitch to Princeton Press, June 2026) and from the user's approved Kurose-pass on Ch 1 of his book.

This profile is editorial-additive: it does not override `voice_profile.md` (mean ~21 words, claim-first topic sentences, active voice, em-dash ban, AI-rhetoric avoidance). It refines what "warmth" and "rhythm" mean in concrete terms and provides red-team criteria for sentence-level audits.

---

## Positive Traits (what to match)

1. **Warm teacher-to-student register.** Writes like a teacher who knows a specific student is reading, not like an academic addressing a committee.
2. **Mixed sentence rhythm.** Short declaratives intercut with longer flowing sentences. Sample target distribution from approved prose: 8 / 10 / 29 / 11 / 33 / 14 / 31 / 14 words across one paragraph. Avoid runs of 3+ sentences of similar length.
3. **First-person "I" intrusion is welcome** where it is the most honest framing. Example: "I taught it that way myself for years." Use sparingly, as a signal of author presence, not a default.
4. **Concrete-before-abstract.** A vivid example or specific image comes BEFORE the named abstraction whenever possible. Show first, name second.
5. **Plain language.** Jargon only where it carries technical weight. Never as decoration.
6. **Active voice, present tense, direct verbs.** No exceptions in narrative prose.
7. **Reader engagement.** Occasional "you" or rhetorical pivot welcome, sparingly, in introductions only.
8. **Topic sentences that hook.** Open with a concrete claim, not a definitional preview. "A student trained on this framework does three things" hooks; "The framework's payoff is what students learn to do with it" previews.
9. **Specific names and numbers.** "10 Mbps bottleneck under CUBIC with a 200-packet queue" over "an experiment configuration." Named protocols, named scales, named people.

---

## Red-Team Criteria (what to flag)

Use these aggressively during sentence-level voice audits.

1. **Abstraction-led openers.** Sentences opening with a NAMED ABSTRACTION before grounding it. "The four invariants name..." (bad) vs. "TCP makes the structure visible. The 1974 Cerf-Kahn paper fixed..." (good).
2. **Stacked clauses of similar length.** 3+ clauses in one sentence carrying equal weight flatten rhythm into explanatory monotone.
3. **Repeated syntactic patterns.** Consecutive sentences using the same structure (e.g., three sentences all starting "X is Y" or "X does A, B, and C") become AI-recognizable parallelism.
4. **AI-rhetoric tells.** Same list as `voice_profile.md` § AI-Rhetoric Avoidance, repeated here for fast reference: `not X but Y`, `rather than X`, `instead of X` (when contrast is rhetorical, not factual), `in essence`, `fundamentally`, `at its heart`, `a testament to`, `truly`, `genuinely`, `indeed`, `crucially`, `notably`, `importantly`, `precisely because`, `X meets Y` framings, `on one hand / on the other hand`.
5. **Academic stiffness as throat-clearing.** Constructions like `This is the choice...`, `This lens explains...`, `This combination of X and Y...`, `Tying the framework together is...`, `The framework's payoff is...`, `gets operationalized`, `chapter by chapter through a structural device` — these are placeholder-shaped sentences where a direct verb would land harder.
6. **Sentences over 35 words in narrative prose.** Chapter-list bullets and credentialing prose can run longer for density (40–50 words acceptable there); narrative paragraphs cannot.
7. **Buried main clauses.** Subject and verb delayed behind stacked modifiers. "Putting themselves in the shoes of the pioneers, students see..." (bad) vs. "Students step into the shoes of the pioneers and see..." (good).
8. **Em-dashes (`---`).** Use colons, parentheses, semicolons, or sentence breaks instead.
9. **Preview-style topic sentences.** Sentences that describe what the section will cover rather than land the section's claim. "The manuscript runs seventeen chapters in seven parts" describes; "Chapter 1 puts the framework on the page" lands.
10. **Named term before its gloss when the gloss should come first.** "The book operationalizes the first capability chapter by chapter through a structural device it calls a pioneer arc" (bad — heavy setup, name late). "Each chapter is built as a **pioneer arc**: a chronological trace..." (good — name first, gloss immediate).
11. **Slogan-style fragment closers.** "The framework's loop closes." or "That is the claim-evaluation skill the book teaches." Punchy fragments at paragraph end are an AI tic that breaks the established rhythm. Close on a complete sentence carrying the claim.
12. **Chains of short staccato sentences.** The failure mode when iterative audits over-correct: splitting one flowing 50-word sentence into five 10-word sentences produces a machine-bulleted feel. Re-merge with semicolons or comma-joined clauses to restore rhythm. The fix for one long sentence is usually two medium sentences, not five short ones.

---

## Audit Workflow

Sentence-by-sentence pass through the document:

1. **Flag** every sentence matching any red-team criterion. Report line, issue category, exact quote, one-line why.
2. **Triage**: separate fixes that improve voice from fixes that would over-correct (rule 12). Some flagged constructions are appropriate to context (chapter-list bullets, credentialing density, factual negations like "students cannot derive...").
3. **Rewrite** flagged sentences. Test each rewrite against rule 12 — is it still part of a varied rhythm, or did the fix produce another staccato chain?
4. **Re-audit** the revised text. Iterate until clean or until further changes risk over-correction.
5. **Stop condition**: declare APPROVED when the prose reads as warm, varied, concrete-led, and free of the named AI-rhetoric tells. Codex-style audits will always find more to flag; stop when the remaining flags push toward staccato fragmentation or strip meaningful contrast.

---

## Voice Anchors (approved examples from this corpus)

Use these as positive reference points when judging whether a rewrite has landed:

**Personal/teacher opener (project description, ¶1):**
> "For two decades, networking has been taught the same way: a layered tour of the Internet's protocols, the mechanics of TCP's three-way handshake, the fields of an 802.11 frame, the steps of a BGP advertisement. I taught it that way myself for years."

**Concrete pioneer-arc passage (project description, ¶5):**
> "TCP makes the structure visible. The 1974 Cerf-Kahn paper fixed the Interface invariant (best-effort datagrams across uncontrolled paths) and the Coordination invariant (distributed, endpoint-only control). That cascade forced State (inferred from ACK signals) and Time (estimated via RTT)."

**Mixed-rhythm Pramana paragraph (project description, ¶ Pramana):**
> "The framework teaches students to ask the right questions. The hard part comes next: running the experiment that answers them. Most students never reach that step, because the cost of setting up even a single networking experiment is high enough that the textbook explanation always wins. My group has been building infrastructure (Pramana) to lower that cost."

Sentence lengths in the Pramana opener: 8 / 10 / 29 / 11. That is the rhythm target.

---

## When NOT to Apply This Profile

- Pure reference material (API docs, bibliographies, table captions): credentialing density and parallel structure are appropriate.
- Math-heavy passages: the rhythm rules yield to notational clarity.
- Chapter-list bullets and tables: density at 40–50 words is appropriate to convey content compactly. Splitting into multiple sentences here over-formats.
- Bio / CV-style author statements: credentialing inventories run long by necessity. Light splits help, but the rhythm rules cannot fully apply.
