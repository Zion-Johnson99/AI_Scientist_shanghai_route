# Deconstruction: Arpit's storytelling style (SIGCSE intro reconciliation)

*From Arpit's edit `40df34d`/`3a28839` reconciling Walter's `6232191` against the AI-drafted intro.
This is the spec for the voice-profile updates that follow. Two layers: (A) Arpit's storytelling
moves, (B) Walter's precision class (already in `walter_edit_gap_analysis_2026-06-30.md`), which Arpit
fully embraced. Both layers go into BOTH `voice_profile.md` (base/Arpit) and `shenker_voice_profile.md`.*

## What changed when Arpit rewrote the AI draft
The AI draft used a terse Shenker register: short punch openers, a "Suppose, instead…" gedanken pivot,
minimal connectives, the loop named once. Arpit kept the *bones* (stakes → problem → loop →
contributions → results) but rewrote the *surface* in a recognizably different voice.

## Layer A — Arpit's storytelling moves (the new rules)

1. **Discourse markers as narrative glue, not filler.** Arpit opens many sentences with explicit
   signposts that steer the reader: "What's worth noting is that…", "However,…", "More concretely,…",
   "The catch is, however,…", "Interestingly,…", "Here,…". The base profile bans "notably/crucially"
   as filler; Arpit uses this whole family deliberately to mark the logical turn. **Rule: connective
   discourse markers are storytelling tools when they signal the argument's move (contrast,
   elaboration, consequence, aside). Keep them; do not strip them as filler.**

2. **Explicit, quotable thesis sentence that echoes the title.** Arpit inserts a standalone claim
   naming the big idea in the title's words: *"This pedagogical transformation from teaching 'how
   networks work' to 'why they work' requires facilitating experiential learning in networking
   education."* **Rule: state the thesis once as an explicit, quotable sentence that uses the
   paper's title concept verbatim. Don't leave the thesis only implied.**

3. **Direct research-statement framing over indirect narrative pivots.** Arpit replaced the gedanken
   "Suppose, instead, that generating the data were cheap" with *"This paper explores the effect of
   lowering the data-generation cost (i.e., student time) on learning outcomes. More concretely, it
   explores how the usage of Pramana… could facilitate experiential learning…"* **Rule: say what the
   paper does directly ("This paper explores / shows / argues…") rather than via a "Suppose…"
   thought-experiment. (This OVERRIDES Shenker's gedanken-pivot preference for Arpit's register.)**

4. **Liberal i.e./e.g. parentheticals for inline precision and examples.** "(i.e., the how)",
   "(i.e., student time)", "(i.e., time saved)", "(e.g., Pinot, Fabric)". **Rule: use i.e. to gloss a
   term in the reader's words and e.g. to name concrete instances, inline, freely.**

5. **Deliberate repetition of the central term for cohesion.** "Experiential learning" recurs ~6
   times in the intro, echoing the title at each structural beat. **Rule: repeating the central
   title concept across beats is cohesion, not redundancy; the de-duplication instinct does not apply
   to the load-bearing thesis term.**

6. **Longer, explanatory, qualified sentences; light emphasis tolerated.** Arpit's sentences run
   longer and more discursive, with embedded "that"/"which" clauses, and he tolerates a light
   emphasis word ("what a student *truly* understands", "*truly* needs to learn"). **Rule: in this
   register, explanatory length is fine, and a sparing emphasis intensifier ("truly") is permitted
   where it marks the stakes — it is NOT auto-banned like "novel/significant".**

7. **One sentence per source line.** Workflow convention (each sentence on its own line in the .tex
   source) for easier diffing/editing. **Rule (formatting, not voice): when editing Arpit's papers,
   keep one sentence per source line.**

## Layer B — Walter's precision class (Arpit adopted all of it)
Carried verbatim from `walter_edit_gap_analysis_2026-06-30.md`; Arpit kept every one:
8. **Calibrated hedges on empirical universals** (takes→can take, means→typically means, is→often is).
9. **Named referents** (no vague it/this/these/that <noun>; name the antecedent).
10. **Thing-vs-process & abstract-vs-concrete disambiguation** (generating the data, not the data;
    cost = student time).
11. **Explicit numbers and named actors** (a host, respondents, participants; "about 20%").

## The reconciliation of conflicts (how A and B coexist with the base/Shenker rules)
- **Discourse markers:** base profile's "delete crucially/notably" is RELAXED for Arpit/storytelling
  — keep markers that signal a logical move; still cut pure throat-clearing ("It should be noted that"
  with no move).
- **Directness vs Shenker gedanken:** Arpit's "This paper explores…" overrides Shenker's "Suppose…"
  for Arpit's register; Shenker's profile keeps the gedanken as an OPTION, not the default.
- **Em-dash tension (FLAG):** Arpit kept Walter's em-dash ("success report---the reasoning…") this
  pass under "integrate Walter's edits as is." This conflicts with Arpit's standing no-em-dash rule.
  Resolution for the skill: the no-em-dash rule remains Arpit's default, BUT it is NOT self-enforcing
  across co-author edits — re-apply it after any collaborator pass. (For THIS paper, the em-dash
  stays because Arpit instructed "integrate Walter's edits as is.")
- **"truly":** moved from banned to "sparing, for stakes" in Arpit's register only; Shenker keeps it
  closer to banned (Shenker's diction is plainer).

## Net: how Arpit's register differs from pure Shenker
Arpit = Shenker's intuition-first + calibrated-hedging bones, PLUS a more guided, signposted,
explanatory surface (discourse markers, explicit thesis-naming, direct "this paper" framing, i.e./e.g.
glosses, deliberate term repetition). It is warmer and more reader-led than terse Shenker, and more
direct than Shenker's gedanken indirection.
