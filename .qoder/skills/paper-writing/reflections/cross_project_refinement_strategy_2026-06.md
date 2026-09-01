# Cross-project refinement strategy: paper-writing skill, viz skill, voice profile

*Synthesizes writing-process feedback Arpit gave across three projects (June 2026) into a concrete
plan for refining the `/paper-writing` skill, the `/viz` (data-visualization) skill, and the voice
profile. Written 2026-06-25.*

## Sources consolidated
1. **SIGCSE Pramana paper** (this paper, agentic-thin-waist/docs/SIGSCE_Pramana):
   `reflections/skill_gap_analysis.md` (16 gaps), `reflections/session_retrospective.md`,
   `reflections/jaber_process_feedback.md`, `synthesis/cse_voice_profile_v2.md` (the exemplar voice
   profile, quotation-grounded).
2. **Broadband affordability** (BQT-corpus/bb-affordability): `paper-writing-reflections.md` (9 gaps),
   `brief-draft/sigcomm_voice_profile.md` (per-artifact exemplar profile), `brief-draft/feedback-for-laasya.md`.
3. **Pramana HotNets** (agentic-thin-waist/docs/Pramana_Hotnets): no skill-reflection file exists yet;
   its `project_context.md` is a standard context. **Action: backfill a reflection there, or confirm
   its lessons are already covered below.**

## The headline: two independent sessions converged on the same #1 gap
Both projects, worked in separate sessions, landed on the same top finding: **the skill teaches how to
build a sound argument, but not how to sound like the specific author/venue without sounding like AI.**
Both independently proposed (a) per-artifact voice profiles derived from real exemplar documents, and
(b) an external auditor used with an "apply-genuine / decline-overreach" discipline. Convergence from
two directions makes these the safest, highest-priority changes.

## Merged gap taxonomy (deduped; ✦ = both projects found it independently)

### Cluster 1 — Anti-AI voice (dominant; near-zero current coverage)
- ✦ **No "sounds like AI" audit.** Consolidated AI-tell catalog from both projects:
  - "Most work does X; we do Y" / "Unlike prior work, we…" positioning binary (SIGCSE).
  - Over-balanced symmetric constructions ("some X are not Y because…; some non-X are Y because…") (broadband, the #1 tell there).
  - Schematic "two-X / three-X" scaffolding that reads like an outline ("It has two halves…").
  - Rule-of-three for rhythm, not meaning.
  - Cleft flourishes ("What remains is…", "What is missing is…").
  - Manufactured-profound closings ("the work that remains is execution").
  - Anthropomorphized tools / abstract nouns as actors ("the analysis surfaced a gap" → "we found").
  - Tidy summary-restatement closings.
- **Over-correction into sterility (additive repair).** A subtractive cleanup (cut em-dashes,
  antithesis, aphorisms) can strip first-person warmth and read *more* like AI. The default repair for
  "sounds like AI" is usually to ADD first-person agency and concrete actors, not delete further. (broadband)
- **First-person agency is the primary humanizing lever** for non-academic registers ("we found / we
  built / my student and I" over abstract-noun subjects and tool-as-actor). (broadband)
- **Slogan/flourish/aphorism ban**, absolute, with a kill-list. (SIGCSE)

### Cluster 2 — Per-artifact / per-author voice calibration (skill assumes one universal voice)
- ✦ **Derive a quotation-dense voice profile from named exemplar documents per artifact**, then audit
  every sentence against THAT, not the generic profile. Exemplars = the author's own papers in the
  target register (broadband: SIGCOMM'23/'24; the prior Benton post) or the venue's closest accepted
  papers (SIGCSE: six CSE exemplars). Two instances already exist: `cse_voice_profile_v2.md`,
  `sigcomm_voice_profile.md`. The generic `voice_profile.md` is the fallback.
- **Parallel-artifact register differentiation + convergence check.** The same findings rendered as
  brief / blog / paper must stay in different registers; read them side by side and catch the blog
  drifting into the paper's detached voice. (broadband)

### Cluster 3 — Punctuation and grammar hygiene
- **Hard no-em-dash rule, in every artifact, overriding any imported exemplar.** (both; broadband
  caught an imported profile silently overriding the standing rule.)
- **After any punctuation/em-dash swap, re-scan for comma splices and comma pile-ups.** (broadband)

### Cluster 4 — Evidence and honesty
- **Reproducible-numbers gate:** every number regenerates from a script; cite only its outputs; lock
  before writing. (SIGCSE)
- **Ground every system/empirical claim against the actual artifact/repo, not plausible prose.** (SIGCSE)
- **Evidenced-vs-afforded modality; limits as scope not threats; the honest result is the strongest.** (SIGCSE)
- **IRB/ethics statement grounded in the real determination.** (SIGCSE)

### Cluster 5 — Process and external review
- ✦ **External auditor + reconcile.** Run an external critic (Codex) each iteration; apply genuine
  catches, decline overreach, never let it redefine the author's voice. Operational: hard `timeout`,
  output to a file (not `| tail`), manual audit as fallback (it can hang). (both)
- **Cross-artifact fact sync + proactive supersession:** one source-of-truth number table; when a
  number changes, grep every artifact AND sent correspondence; flag superseded numbers already sent. (broadband)
- **Render-check before external send:** audit what actually compiles into the output (BibTeX
  `note`/`howpublished`, anything outside verified comments); `pdftotext | grep` for TODO/verify/
  placeholder/draft. (broadband; a "to be verified" bib note nearly went to a Senate contact.)
- **VCS/Overleaf workflow:** branch, PR, never commit to the synced `main`, commit incrementally. (SIGCSE)

### Cluster 6 — Strategy and framing
- **Track/category fit by contribution + accepted exemplars + CFP** (ERT vs CER), beyond format. (SIGCSE)
- **Multi-paper portfolio boundary:** what belongs in which paper; hold the design line; "not a
  contribution here" as principled. (SIGCSE)
- **Altitude separation:** philosophy / artifact / enabler. (SIGCSE)
- **Double-blind hygiene for self/companion works + repo URLs.** (SIGCSE)
- **Cross-disciplinary accessibility audit; name the abstraction as an activity.** (SIGCSE)

---

## Refinement plan, per target

### A. `/paper-writing` skill
**New files**
- `author_profile/ai_tell_audit.md` (P0) — the consolidated AI-tell catalog (Cluster 1), run as a
  distinct GATE dimension on every prose edit. Format: quote offending sentence → name the tell →
  plain first-person rewrite. MUST include the two counterweights: (i) over-correction sterilizes,
  repair by adding first-person agency; (ii) first-person agency is the primary humanizing lever.
- `voice_calibration.md` (P0) — the per-artifact exemplar method (Cluster 2): name target register +
  1–2 exemplar docs the author actually wrote (or accepted venue papers); extract a quotation-dense
  one-page profile; audit sentence-by-sentence against it; generic `voice_profile.md` is fallback.
  Reference `cse_voice_profile_v2.md` and `sigcomm_voice_profile.md` as worked instances.

**Edits to existing files**
- `voice_profile.md` (P0): hard no-em-dash rule + post-swap comma-splice/pile-up scan; the "X, not Y"
  and "Most work does X; we Y" template bans; elevate first-person agency for non-academic registers.
- Venue Adaptation (P1): add a parallel-artifact register matrix (artifact→audience→register→exemplar)
  + the side-by-side convergence check.
- `intervention_types.md` / new pipeline stage (P1): "external auditor + reconcile" with the
  hold-the-voice rule and the operational notes (timeout, file output, fallback).
- Integration stage (P1): cross-artifact fact-sync + supersession; render-check before external send.
- Evaluation checklist (P1): reproducible-numbers gate; ground-claims-against-artifact; evidenced-vs-
  afforded + honest-result; IRB/ethics statement.
- Brainstorming / strategy (P2, but high value): track-fit; multi-paper boundary; altitude separation;
  double-blind self-citation hygiene; cross-disciplinary accessibility audit; abstraction-as-activity.

### B. `/viz` (data-visualization) skill
- **Reproducible-figure gate (P1):** every figure regenerates from a committed script; the paper cites
  only regenerated figures (mirrors the numbers gate). Already partly implied by execute mode; make it a rule.
- **Render-fit check in `analyze` mode (P1):** render at the target column width and verify it fits the
  margins, no element overlap (legend over data), and every arrow lands on a real target. This session
  shipped a Figure 1 that overran the column with arrows going nowhere; it took a screenshot to catch.
  Add "render at final width and inspect the rasterized output" to analyze mode.
- **Palette/style inheritance (P2):** execute mode should pull the paper's palette and rcParams (serif,
  Paul Tol) so figures match the document; never let `sns.set_theme()` defaults leak in (already
  warned, reinforce).

### C. The voice profile (artifact)
- Reframe from one universal lab profile to a **family of per-artifact exemplar profiles** created via
  `voice_calibration.md`; ship `cse_voice_profile_v2.md` and `sigcomm_voice_profile.md` as templates.
- Bake in the no-em-dash hard rule and the AI-tell catalog as the audit input.
- Encode the **dual failure mode** explicitly: over-cleaned sterility vs over-eager-auditor chattiness;
  the profile's job is to hold the author's specific voice between those poles.

## Sequenced rollout
1. **P0 first (both projects converged):** `ai_tell_audit.md`, `voice_calibration.md`, the no-em-dash +
   post-swap rule. These address the dominant, repeated failure and are exemplar-grounded.
2. **P1 process + evidence:** external-auditor-reconcile, reproducible numbers/figures, ground-in-artifact,
   render-check, cross-artifact sync, viz render-fit.
3. **P2 framing:** track-fit, multi-paper boundary, altitude, double-blind, accessibility.
4. **Backfill** the HotNets reflection (or confirm coverage), and add the new files' pointers to each
   skill's SKILL.md so the gates actually fire.

## One-line synthesis
Across three projects the constant is the same: the skill builds the argument well but does not yet make
Claude sound like *this author, in this register, without sounding like AI*. The fix is a per-artifact
exemplar voice profile plus an anti-AI audit whose default repair is adding first-person agency, run
with an external critic that is filtered, never obeyed.
