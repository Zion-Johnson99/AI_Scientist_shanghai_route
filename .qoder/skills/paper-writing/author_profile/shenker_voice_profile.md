# Shenker Voice Profile

A voice profile for the conceptual, proposal, and systems-design registers, complementing `voice_profile.md`. Use it when the user explicitly asks for "Shenker voice" / "Shenker pass," or when the paper argues a position, proposes an architecture, or designs and evaluates a networked system in the tradition of Scott Shenker's writing.

Mined sentence-by-sentence from three papers spanning Shenker's registers:
- **[FDI]** "Fundamental Design Issues for the Future Internet," *IEEE JSAC* 13(7), 1995 (Shenker, sole author). The **conceptual / position** register — purest sample.
- **[OF]** "OpenFlow: Enabling Innovation in Campus Networks," *ACM CCR* 38(2), 2008 (McKeown et al., 8 authors). The **proposal / vision** register.
- **[CAN]** "A Scalable Content-Addressable Network," *ACM SIGCOMM* 2001 (Ratnasamy, Francis, Handley, Karp, Shenker). The **systems-design + evaluation** register.
- **[WTF]** "The Case for an Internet Primitive for Fault Localization," *ACM HotNets* 2022 (Sussman, Marx, Arun, Narayan, Alizadeh, Balakrishnan, Panda, Shenker). The **modern HotNets position** register — Shenker as senior author, 2022. The most directly relevant sample for a present-day HotNets submission, and proof that the invariant fingerprint holds across a 27-year span (the "if not" upgrade of R18, the crux/lever of R37, the humility moves of R50 all recur verbatim-in-spirit).

This profile is a **register switch**, not an editorial overlay. Unlike `kurose_voice_profile.md` (which only refines warmth and rhythm and keeps every base rule), this profile *inverts* several base-profile rules because the base is tuned for terse empirical systems papers and Shenker's voice is tuned for architectural reasoning. The inversions are named in R-rules below. The profile is deliberately dense: **64 numbered rule-sets** (R1–R64, plus the R51–R57 anti-AI addenda), grouped, each independently auditable, each backed by evidence from the corpus. The past failure mode of voice profiles has been under-specification that collapses to "write clearly"; this one resists that.

---

## The three registers, and the invariant fingerprint

Shenker's voice adapts its register to the paper's job, but a core set of moves appears in all three papers. Those invariants are the fingerprint; the rest are register-specific.

| Register | Paper | Job | What changes |
|---|---|---|---|
| **Conceptual / position** | [FDI] | Frame a debate, weigh alternatives, refuse to over-resolve | Heaviest hedging; question-titled sections; the Gedanken model; first-person "I"; longest sentences |
| **Proposal / vision** | [OF] | Sell a pragmatic compromise and a future | Compromise framing; criteria-first bulleted goals; concrete persona; aspirational "we hope" close |
| **Systems-design** | [CAN] | Design, then measure | Assertive on results; intuition-first mechanism prose; numbered procedures; trade-off deferred to future experience |
| **Modern HotNets position** | [WTF] | Provoke a debate, propose a primitive, specify little | Typeset position statement; "stir up a debate" goal; cross-X tricolon refrain; principled under-specification; Internet-precedent analogy; front-loaded limitations; conventional-wisdom challenge; more conversational (contractions, shared-experience questions, a playful acronym). A refinement of the conceptual register — see group S (R58–R64). |

**The invariant fingerprint (present across all four papers, 1995–2022):** the focus-narrowing disclaimer (R3); the explicit purpose sentence (R4); calibrated hedging on *rationale* (R17); the "if not" confidence upgrade (R18, in [FDI] 1995 and [WTF] 2022); the trade-off that refuses to over-decide (R40–R42); the "Of course… at the cost of" concession (R46); the crux/lesson markers — "the point to take away is…", "the bottom line is…", "the key idea is…" (R37, R48); define-by-naming (R38); preview-the-count enumeration (R35); justify-by-Internet-precedent analogy (R62); honest-limitation statements (R-Q, R63); "Recall that…" reader orientation (R25); a single organizing lever or crux (R37); the one-vivid-word (and one-playful-acronym) diction (R47); and the confidence-plus-humility tonal balance (R50).

---

## §1. The base-profile inversions (read before applying)

| Base rule | Shenker register | Rule |
|---|---|---|
| Mean ~21 words, max ~40 | Mean ~28–32, high variance; long sentences fine iff every clause advances one argument | R6 |
| Zero hedging | Calibrated hedging on rationale is the core craft; assert only measured results | R17, R19 |
| No rhetorical questions outside intro | Question-titled sections drive the conceptual register | R27 |
| Always "we," never "I" | Three-pronoun system: we / I / one | R13–R15 |
| Headings are claims | Headings may be questions (conceptual) or tasks (systems) | R27 |
| Paragraphs 4–6 sentences | Essayistic 6–10 sentence paragraphs | R30 |

**Kept from base, no exception:** em-dash ban (use colon/comma/parens/semicolon; do not import [OF]'s hyphen-dash parentheticals or [FDI]'s em-dashes); active voice for claims; no filler adjectives ("novel," "significant," "promising"); named-over-vague; AI-decoration bans (`a testament to`, `X meets Y`, `truly`, `genuinely`).

**Conceptual-vocabulary exception:** `fundamentally`, `in essence`, `at the core of` are load-bearing in this voice ("reduce, **in essence**, to the following question" [FDI]; "**at the core of** this trade-off is the central fact" [FDI]; title: "**Fundamental** Design Issues"). Permit them *only* when they mark a real reduction or invariant. Delete-test: remove the word; if a claim about what is essential/foundational is lost, keep it; else cut. Pure decoration (`at its core` as filler, `truly`) stays banned.

---

## §2. The rule-sets (R1–R64)

### A. Register and framing (R1–R5)

**R1. Choose the register first.** Decide conceptual / proposal / systems before drafting; it sets hedging level, heading style, and closing. Do not mix the proposal "we hope" close onto a conceptual analysis, or hedge a measured CAN result.

**R2. Honor the invariant fingerprint.** Whatever the register, include the fingerprint moves listed above. Their absence is the fastest tell that prose is off-voice.

**R3. The focus-narrowing disclaimer (invariant).** State early what the paper is *not* doing, then what it *is*. "our focus is not on the use of CANs but on their design" [CAN]; "we do not attempt to add to this body of knowledge here… Instead, our focus is on identifying the reasoning and assumptions behind various design approaches" [FDI]. This narrows scope honestly and pre-empts the "why didn't you do X" reviewer.

**R4. State the paper's purpose in one explicit sentence (invariant).** "The purpose of this paper is to articulate some of the basic issues in what has been an underarticulated disagreement…" [FDI]; "We started our investigation with the question: could one make a scalable peer-to-peer file distribution system?" [CAN].

**R5. Apply the conceptual-vocabulary exception** (see §1) rather than blanket-deleting "fundamental"/"in essence."

### B. Sentence mechanics (R6–R12)

**R6. High mean, high variance.** Target ~28–32 words mean with deliberate swings. Measured [FDI] opener: 13 / 31 / 52 / 42 / 28 / 30 words. Do not flatten to uniform length (that is the base profile's job, not this one).

**R7. Short punch opener, then expand.** Open a section or paragraph with a short declarative, then build. "There are few technological success stories as dramatic as that of the Internet." (13w) [FDI]; "The basic idea is simple: …" [OF]; "Intuitively, routing in a Content Addressable Network works by following the straight line path…" [CAN].

**R8. Build long sentences by coordination, not subordination-stacking.** Join independent clauses with semicolons and `and`, and drop in `for example` appositives. "…grown into a social institution of substantial import; for example, one national newsmagazine has a regular column on the Internet, and many advertisements now include an electronic mail address…" [FDI].

**R9. Fronted concessive opener.** Begin long sentences with `While…`, `Even though…`, `Although…`, `Despite…` to grant ground before advancing. "Even though the Internet is still extremely small compared to the telephone and cable TV networks…, it has clearly joined them…" [FDI].

**R10. Fronted negation for emphasis.** Front a negated clause to tee up the positive payload. "far from being the exclusive concern of a small technical community, [the design choices] will have far-reaching implications for the general public" [FDI].

**R11. Colon as the workhorse.** Use a colon to introduce a reduction, definition, or list far more than the base profile does. It is the primary em-dash replacement: "reduce, in essence, to the following question: how happy does this architecture make the users?" [FDI].

**R12. Parenthetical aside for concession or gloss.** Insert short concessions and qualifications in parentheses rather than as separate sentences. "While there remains some (quite justified) skepticism…" [CAN]; "(if at all)" [CAN]; "(this author also pleads guilty to this crime)" [FDI].

### C. The three-pronoun system (R13–R16)

**R13. "We" = the moves this paper makes.** Reserve "we" for steps the authors take. "We can illustrate this by…"; "We now contrast these two options"; "We will first describe the three most basic pieces of our design" [CAN].

**R14. "I" = contestable personal choice or credit.** Rare, deliberate, usually footnoted, used where the reader could disagree. "Here I am equating the happiness of users with the performance of their applications" [FDI]; "While I have freely stolen the insights of D. Clark and L. Zhang…" [FDI].

**R15. "One" = impersonal design-space generality.** Carries claims about what any designer could do. "One can address these problems without changing the basic Internet architecture…"; "if one were willing to incur an increase in… neighbor state…" [CAN]. Do not collapse "one" into "we."

**R16. Address "the reader" directly to maintain orientation.** "the reader must remember that the coordinate space wraps" [CAN]; "recall that nodes that are adjacent in the CAN might be many miles… away from each other" [CAN].

### D. Confidence and hedging (R17–R20)

**R17. Grade confidence to evidence using the ladder.** Build modality from: *structural certainty* ("Clearly,", "Certainly", "the central fact that") → *strong expectation* ("we expect that", "is likely to") → *plausible* ("it seems plausible, if not probable, that", "it appears that") → *open* ("This is certainly a debatable point", "it is not clear that") → *conceded limit* ("Of course,", "impossible to gauge precisely"). Also use "**Surprisingly**, this question has received rather little explicit attention" [FDI] to flag a notable gap that licenses the paper without an empirical claim.

**R18. The "if not" upgrade.** Raise confidence one notch inside a phrase: "plausible, **if not** probable" [FDI]. The same construction recurs 27 years later: "well-specified systems are **hard, if not impossible,** to deploy in environments made up of components managed and built by multiple independent entities" [WTF]. Hedging with conviction; a fingerprint marker.

**R19. Hedge the rationale, assert the measurement.** In the systems register, design *reasoning* is hedged but measured *results* are stated flat: "placing 4 nodes per zone can reduce the per-hop latency by about 45%"; "RTT weighted routing lowers the per-hop latency by between 24-40%" [CAN]. Never hedge a number you measured.

**R20. Conjecture markers carry honest belief.** "We believe a similar functionality would be equally valuable…"; "Our interest in CANs is based on the belief that a hash table-like abstraction would give… a powerful design tool"; "We conjecture that many large-scale distributed systems could likewise benefit…" [CAN]. `We believe` / `We conjecture` are permitted here (the base profile bans them).

### E. Connectives (R21)

**R21. Keep the logical joints visible.** Do not strip `Thus,` `However,` `Moreover,` `Of course,` `Similarly,` `In particular,` `Nonetheless,` as "connective tissue" — in this register they carry the argument's logic. "Thus, the design choices we make…"; "Nonetheless, despite this uncertainty, at the core of this trade-off…"; "Similarly, the telephony community built a network around an application…" [FDI].

### F. Meta-discourse and cross-reference (R22–R25)

**R22. Roadmap paragraph with parenthetical section pointers (invariant).** "After briefly reviewing the current Internet architecture… (in Section II), we present a criterion… (in Section III). We then discuss whether the Internet should adopt a new service model (in Section IV)…" [FDI]; "We describe our basic design for a CAN in Section 2, describe and evaluate this design… in Section 3 and discuss our results in Section 4" [CAN].

**R23. Forward references promise.** "We will return to these two points in Section V" [FDI]; "We will address the issue… in much greater detail in Section VI" [FDI].

**R24. "In a nutshell, our strategy is…" — one-sentence approach summary.** "In a nutshell, our strategy in attempting to reduce path latency is to reduce either the path length or the per-hop latency…" [CAN].

**R25. Backward references orient (invariant).** "Recall that in Section IV we made two observations"; "Recall that for our simple Gedanken experiment…" [FDI]. Every major section both recalls what is established and names its new question.

### G. Section architecture (R26–R29)

**R26. Question-titled sections (conceptual) or task-titled (systems).** [FDI]: "What Is the Goal of Network Design?", "Why Do We Need to Extend the Service Model?", "Who Chooses the Service for a Flow?", "Do We Need Admission Control?" [CAN]: "Routing in a CAN", "CAN construction", "Node departure, recovery and CAN maintenance." Subsection titles can be named contrasts: *"Implicitly Supplied" versus "Explicitly Requested"* [FDI].

**R27. Recap-advance openers.** Open a section by summarizing the established position, then naming the new question. Template: "We have argued [X], but we have not yet [Y]." "We have argued that the Internet should extend its service model, but we have not yet discussed what services should be added" [FDI]; "At this point, we have argued that the network should offer a service model… However, we have yet to address one fundamental question…" [FDI].

**R28. Handoff closers.** End a section by handing the baton to the next question rather than restating a result. [FDI] §III's opening hands forward: "all of this analysis must start by asking what is the goal of network design?" — the next section's title.

**R29. "We will first… We will then…" staged preview within a section.** "We will first describe the three most basic pieces of our design: CAN routing, construction of the CAN coordinate overlay, and maintenance… We will then, in Section 3, discuss additional design pieces that greatly enhance system performance and robustness" [CAN].

### H. Paragraph architecture (R30–R31)

**R30. Essayistic four-beat paragraphs.** 6–10 sentences shaped Claim → Illustrate ("We can illustrate this by…" / a `for example`) → Complicate (a `However,` or "Weighing against these advantages…" turn) → Qualify (a closing sentence on the matching confidence rung, often `Of course,`). Do not chop into 4-sentence blocks; that breaks the build.

**R31. Intuition-first mechanism prose (systems).** Give the intuition before the formal mechanism. "Intuitively, routing in a Content Addressable Network works by following the straight line path through the Cartesian space from source to destination coordinates" [CAN]. The formal description follows.

### I. Worked examples (R32–R34)

**R32. The 7-step Gedanken template (conceptual).** (1) Announce and disclaim the toy: "Let us consider the following Gedanken experiment…" (2) Minimal scenario: "a single link modeled by an exponential server (rate μ=1)…" (3) Toy numbers: "U₁ = 4 − 2d₁ and U₂ = 4 − d₂…" (4) Compute each option: "V^FIFO = 2 … V^priority = 8/3." (5) Interpret: "Thus the strict priority algorithm delivers a higher value of V at the same bandwidth than FIFO." (6) Extract enumerated lesson (R35). (7) Generalize with caveat: "our simple Gedanken experiment can be generalized to mixtures… with the same conclusions." [FDI].

**R33. The paired micro-example tied to a figure (systems).** Illustrate an abstract rule with a positive and a negative instance immediately. "For example, in Figure 2, node 5 is a neighbor of node 1 because its coordinate zone overlaps with 1's along the Y axis and abuts along the X-axis. On the other hand, node 6 is not a neighbor of node 1 because…" [CAN].

**R34. Interpret the number, not the arithmetic.** The worked figure exists only to make the conceptual claim concrete and unarguable; always follow a computation with the sentence that says what it *means*.

### J. Enumeration (R35–R36)

**R35. Preview the count, then deliver in prose (invariant).** Announce a count, then mark items with `First,` / `Second,` inside running prose (not bullets, in the analytical register). "This lack of elasticity causes two problems. First,… Second,…"; "Our analysis… reveals two other important points… First,… Second,…"; "Recall that in Section IV we made two observations. First,… Second,…" [FDI].

**R36. Numbered procedure (First / Next / Finally) for mechanisms.** "The process takes three steps: 1. First the new node must find a node already in the CAN. 2. Next, using the CAN routing mechanisms, it must find a node whose zone will be split. 3. Finally, the neighbors of the split zone must be notified…" [CAN].

### K. Naming and the organizing lever (R37–R39)

**R37. Coin one organizing lever or crux and run everything through it.** Conceptual: "We will call this quantity V, the efficacy or total utility of an architecture… Much of our subsequent analysis bears on how various design choices affect V" — and admission control is later restated as "which choice maximizes the efficacy V" [FDI]. Systems: isolate the crux — "the peer-to-peer file transfer process is inherently scalable, but **the hard part is** finding the peer from whom to retrieve the file" [CAN]. Position: the lever is a coined primitive plus crux markers — "The **key idea** is for each element to maintain and expose a *succinct summary* of its state"; "The **main challenge lies in** identifying the subset of elements… whose health bits should be inspected"; "The **bottom line is** that no single entity has complete visibility" [WTF]. One lever; restate later questions in its terms. The crux-marker family — `the point to take away is`, `the hard part is`, `the key idea is`, `the main challenge lies in`, `the bottom line is` — is invariant.

**R38. Define by naming (invariant).** Introduce terms with `called` / `termed` / `we call`, often plus a parenthetical gloss. "a chunk (called a zone)"; "Nodes that share the same zone are termed peers"; "We call such indexing systems Content-Addressable Networks" [CAN]; "We use the term Content-Addressable Network (CAN) to describe such a distributed, Internet-scale, hash table" [CAN].

**R39. Assert-property-then-gloss-in-parentheses list.** State each design property and immediately gloss it parenthetically. "Our CAN design is completely distributed (it requires no form of centralized control, coordination or configuration), scalable (nodes maintain only a small amount of control state that is independent of the number of nodes), and fault-tolerant (nodes can route around failures)" [CAN].

### L. Trade-off architecture (R40–R42)

**R40. Name both costs and admit they are unmeasurable (invariant).** "there is a trade-off between the cost of adding bandwidth and the cost of adding the extra mechanism… Both of these costs are impossible to gauge precisely" [FDI].

**R41. The "weighing against these advantages" turn.** "Weighing against these powerful advantages are some practical disadvantages" [FDI]; "Of course, these advantages come at the cost of…" [CAN] (see R46).

**R42. Refuse to over-decide; defer to future experience.** When a trade-off is genuinely open, say so and decline to settle it. "The extent to which the following techniques are applied (if at all) involves a trade-off between improved routing performance… and increased per-node state and complexity. Until we have greater deployment experience, and know the application requirements better, we are not prepared to decide on these tradeoffs" [CAN]; "This is certainly a debatable point, and one that should be debated more extensively than it has" [FDI].

### M. Binary and alternatives (R43–R44)

**R43. Clean binary, name each side, contrast in turn.** "There are essentially two possible answers to this question: the flow can pick the service, or the network can pick the service. We now contrast these two options" [FDI].

**R44. Name and reject the obvious alternative first.** Clear the obvious path before presenting yours, to earn trust. "One approach, that we do not take, is to persuade commercial 'name-brand' equipment vendors… This outcome is very unlikely in the short-term" [OF].

### N. Criteria-first proposal (R45)

**R45. Criteria first, then solution-as-compromise-against-criteria (proposal).** Enumerate the goals the solution must satisfy as a bulleted list, then present the proposal as meeting them. [OF] lists four properties ("Amenable to high-performance and low-cost implementations; Capable of supporting a broad range of research; Assured to isolate experimental traffic; Consistent with vendors' need for closed platforms") then: "This paper describes the OpenFlow Switch, a specification that is an initial attempt to meet these four goals." Frame the proposal as a "pragmatic compromise" [OF], not an optimum.

### O. Concession (R46)

**R46. "Of course, these advantages come at the cost of…" (invariant).** Grant the obvious objection or cost before the reader raises it. "Of course, these advantages come at the cost of increasing the size of the (key,value) database and query traffic… by a factor of k" [CAN]; "Of course, the rate at which new flows can be processed will depend on the complexity… But it gives us confidence that meaningful experiments can be run" [OF].

### P. Diction, lesson extraction, and guarding (R47–R49)

**R47. One vivid or wry word per passage.** Mostly plain technical prose, with a single colorful word that *carries* the sentence (distinct from banned filler that merely decorates). Corpus: "ossified," "a blessing and a curse," "startling and dramatic success," "the larceny is especially egregious," "dire consequences," "Gedanken," "gift economy," "cornucopia," "Not unintentionally, many of these techniques offer the additional advantage of…" [CAN]. The wit can also live in a **playful, self-aware name**: the [WTF] paper names its primitive "WTF" and footnotes it "Where's The Fault? (What did *you* think it stood for?!)". Wry self-deprecation and a single cheeky acronym are welcome; do not cluster vivid words or stack multiple jokes — scarcity is the effect.

**R48. "The point to take away is…" — explicit lesson extraction (invariant).** State the lesson plainly so the reader cannot miss it. "Rather, the point to take away is that if one were willing to incur an increase in… neighbor state for the primary purpose of improving routing efficiency, then the right way to do so would be to increase the dimensionality d" [CAN]; "The point here is that one cannot request access to these link shares; access is implicitly given" [FDI].

**R49. Guard against the wrong inference.** Explicitly head off a misreading of your own data or claim. "One should not, however, conclude from these tests that multiple dimensions are more valuable than multiple realities, because multiple realities offer other benefits…" [CAN].

### Q. Humility and closings (R50)

**R50. The confidence-plus-humility balance, and the register-specific close.** The signature tone: full confidence in the *argument*, explicit humility about its *author and limits* — both halves, always.
- *Humility moves (invariant):* implicate yourself in the flaw you diagnose ("this author also pleads guilty to this crime" [FDI]); over-credit sources by name ("freely stolen the insights of D. Clark and L. Zhang" [FDI]); admit the method's boundary ("our discussion here is nonrigorous and intuitive; our goal is to articulate these issues, not provide analytical resolution of them" [FDI]; "in the interests of simplicity we won't discuss these further here" [CAN]); leave hard questions open ("Clearly, these incentive issues are extremely important and many issues remain unresolved" [FDI]).
- *Close by register:* **proposal** ends on an escalating, concrete "we hope" anaphora — "we hope that OpenFlow will gradually catch-on… We hope that a new generation of control software emerges… And over time, we hope that the islands of OpenFlow networks… will be interconnected" [OF] (three beats, widening scope); **conceptual** ends on an open question plus "many issues remain unresolved"; **systems** ends on a deferred trade-off ("Until we have greater deployment experience… we are not prepared to decide") and a forward-pointing "directions for future work."

---

### R. Anti-AI addenda (R51–R57)

These four close gaps found by codex red-teaming (June 2026): off-voice patterns the R1–R50 set and the original checklist did not catch. They target prose that is grammatical and even Shenker-flavored yet still reads as machine-generated.

**R51. Ban proverb-shaped thesis sentences.** A sentence that poses as wisdom before it says anything ("The window is narrower than it looks"; "a framework is worth only as much as the disagreements it survives") is an AI tell, not a Shenker move. Keep an aphorism only if the very next clause cashes it out in a concrete, analytical claim. Delete-test: strip the aphorism; if no argument is lost, it was decoration.

**R52. Flag symmetry addiction.** The base profile bans `X meets Y`, but polished mirror pairs slip through: "by default ... deliberately," "top-down ... bottom-up," "not the elegance but the cost." A mirrored binary earns its place only when it marks a real design contrast. If the two halves are decorative balance, break the symmetry and name the actual mechanism; demote the second half to a check, not a co-equal slogan.

**R53. Cap abstract-noun cascades.** R37 wants one organizing lever; this enforces it at sentence grain. Do not introduce more than two fresh abstract nouns in one sentence unless each is defined and used distinctly. "the proactive objective forces constraints, every plane answers invariant questions, and a cascade onto the invariants reads off the architectural requirements" pileups five (objective, constraints, questions, invariants, requirements) and bites on none. Keep one organizing noun; make the rest concrete or cut them.

**R54. Ban generic futurist hype verbs.** `promises to`, `stands to`, `is poised to`, `opens the door to`, `is set to`, `has the potential to` are product-copy verbs, not analysis. Replace each with a stated mechanism, a named question, or a confidence-graded claim (R17). "Agents promise to change operations" becomes "Agents change which decisions a closed loop can absorb" or "Whether agents change operations is not yet settled."

**R55. Named deployments must cash out analytically.** In a conceptual intro, do not list vendors, dates, or products unless each name supports a distinct architectural consequence. One named deployment that illustrates a specific commitment (HPE Mist around language-model summarization) earns its place; a census ("Cisco and Microsoft ship comparable features, and large providers run agents") is market motion standing in for argument. Compress the census to "vendors are already shipping such systems."

**R56. No deadline claims without a mechanism.** R54 catches hype verbs; this catches timeline theater (`months, not years`, `a narrow window`, `running out of time`). If prose names a time horizon, it must also name the adoption or lock-in mechanism that sets it. "Architectures ossify once shipped, so the time to analyze is now" is licensed; a bare "months, not years" is not.

**R57. Cap modifier stacks.** R53 caps abstract nouns; this caps the generated-looking noun stack. Use at most one novel compound modifier before a noun unless the phrase is already a term of art. "cross-layer, cross-entity judgments" and "per-entity belief layer" are acceptable as coined terms; do not chain a third ("low-dimensional per-entity behavioral signature layer") without defining it.

### S. Modern HotNets position register (R58–R64)

Mined from [WTF] (HotNets 2022, Shenker senior author). These refine the conceptual register for a present-day HotNets submission. They are the highest-value rules for a HotNets draft; apply them on top of the conceptual-register rules (R6, R17, R26–R28, R32, R50-conceptual), not instead of them.

**R58. The typeset position statement.** Elevate the purpose sentence (R4) into an explicit, italicized, labeled position statement, set off from the prose. "This brings us to our **position statement**: *The Internet needs a universal fault localization primitive that is cross-layer, cross-domain, and cross-application.*" [WTF]. The position statement is one sentence, names the gap and the proposed primitive, and is quotable on its own.

**R59. Frame the goal as provocation, not resolution.** A HotNets paper starts an argument; say so. "Our goal is to **stir up a debate** about the value and practicality of creating a succinct information interface to localize faults…" [WTF]. This is the HotNets sharpening of R3 (focus-narrowing) and R42 (refuse to over-decide): the deliverable is a well-posed debate, not a settled answer.

**R60. The cross-X tricolon refrain as the organizing lever.** Coin a memorable multi-part phrase, gloss each part with a `because` clause, and reuse it verbatim as the paper's refrain (this is R37's lever realized as a slogan, and R39's assert-then-gloss elevated to structure). [WTF]: "cross-layer, cross-domain, and cross-application," glossed as a bulleted list — "*cross-layer*, because a fault could occur anywhere from the physical layer to an app-layer library; *cross-domain*, because most applications use services across different organizations; *cross-application*, because many components are shared" — then repeated at every structural beat (abstract, position statement, overview, conclusion).

**R61. Defend under-specification as a principle, not a gap.** When the design deliberately leaves things open, argue that full specification is *impossible* here, not merely skipped, and make the looseness the contribution. "WTF is **intentionally under-specified**: it does not define what constitutes an element error… This lack of specificity is not a matter of choice… it is impossible to know in advance because whether or not anomalous behavior at an element leads to an application problem depends on the application's semantics." Close on the virtue: "by adopting the concept of health-bits and specifying very little, WTF provides a design that is both useful… and is deployable incrementally" [WTF].

**R62. Justify by Internet-precedent analogy (invariant for architecture papers).** Defend a design choice by analogy to a historically successful Internet mechanism (IP, BGP, ECN). "This approach is similar to many successful Internet protocols including IP and BGP, which include fields with understated semantics and whose use has evolved… while the 1-bit explicit congestion notification (ECN) mark is standardized, each router can determine if it is congested using its own algorithm; *i.e.*, the bit is standardized, but the logic used to set it is not" [WTF]. The analogy does real argumentative work: it transfers the credibility of a deployed protocol to the new proposal.

**R63. Front-load an honest limitations enumeration.** State plainly and early — in the overview, not buried in a final paragraph — what the proposal cannot do. "WTF cannot localize all faults… WTF cannot localize problems that… WTF is not designed to work in the face of Byzantine faults… WTF may not always precisely identify the root cause… Finally, because WTF assumes that elements record health bits for a bounded time, WTF cannot be used to localize faults that happened in the distant past" [WTF]. This is the HotNets sharpening of the humility system (R50): a frank, enumerated "here is what it can't do" earns the reader's trust to consider what it can.

**R64. Challenge conventional wisdom explicitly.** Name the prevailing assumption, then position the work against it. "**Conventional wisdom dictates** that to be useful, a system must be precisely specified… Our work builds on the observation that well-specified systems are hard, if not impossible, to deploy in environments made up of components managed and built by multiple independent entities" [WTF]. Pair with the relatable, shared-experience question that opens many HotNets intros: "Haven't we all been in videoconferences where someone freezes and everyone wonders if it's something at their end or elsewhere?" [WTF]. The modern register tolerates contractions and direct second-person address that the 1995 [FDI] register avoids; calibrate conversationality up for HotNets, down for archival venues.

---

## Red-team checklist (flag prose that drifted off-voice)

Report line, rule number, quote, one-line fix.

1. Flat over-assertion on a *rationale* claim where support is argument, not measurement → R17, R19.
2. A genuinely two-sided trade-off resolved cleanly, or settled when it should stay open → R40–R42.
3. A toy model presented as reality, no disclaimer → R32, R3.
4. Topic-heading where a question (conceptual) or the recap-advance opener belongs → R26, R27.
5. No single organizing lever or crux; the argument wanders → R37.
6. Stranded humility (all hedge, no position) or stranded arrogance (all assertion, no credit, no admitted limit) → R50.
7. Conceptual vocabulary used as decoration (delete-test fails) → §1 exception.
8. Pronoun collapse — everything "we," losing "one" / "I" → R13–R15.
9. Logical connectives stripped as filler → R21.
10. Uniform sentence length, low variance → R6, R7.
11. Paragraphs chopped to 4 sentences, breaking the four-beat arc → R30.
12. A measured result that got hedged ("seems to reduce latency") → R19.
13. Em-dashes, or [OF]-style hyphen-dash parentheticals → §1 (kept rule).
14. Pure-decoration AI tells (`a testament to`, `X meets Y`, `truly`) → §1 (kept rule).
15. An abandoned reader — a reasoning leap with no "Recall that…" / "We can illustrate this by…" / "Intuitively…" bridge → R16, R25, R30, R31.
16. A result paragraph with no "the point to take away is…" and no guard against misreading → R48, R49.
17. A proverb-shaped thesis sentence that does not immediately cash out in a concrete claim → R51.
18. A mirrored binary or antithesis that sounds neat but marks no real design contrast → R52.
19. A sentence carrying 3+ fresh abstract nouns, none defined or used distinctly → R53.
20. A generic futurist hype verb (`promises to`, `poised to`, `opens the door to`) → R54.
21. A vendor/product census that does not cash out to a design consequence → R55.
22. A deadline or time-horizon claim with no adoption/lock-in mechanism → R56.
23. More than one metaphor family in a single intro paragraph (residue / script / window / spine together) → R47, R57.
24. A HotNets paper with no typeset, quotable position statement → R58.
25. A position paper that claims to settle the question rather than open a debate → R59, R42.
26. A coined primitive with no reused refrain, or a refrain glossed once and then dropped → R60.
27. Deliberate under-specification presented as an unaddressed weakness rather than defended as principled → R61.
28. A novel architecture claim with no appeal to an Internet precedent (IP/BGP/ECN) where one would carry the argument → R62.
29. Limitations buried in the last paragraph instead of front-loaded in the overview → R63.
30. A contribution framed in a vacuum, without naming the conventional wisdom it pushes against → R64.

---

## Worked transformations (base voice → Shenker voice)

**Taking a position on an unsettled design choice:**
- *Base:* "Extending the service model outweighs its cost. We show that bandwidth savings exceed the added mechanism cost."
- *Shenker [conceptual]:* "There is a trade-off between the cost of adding bandwidth and the cost of the extra mechanism, and both are impossible to gauge precisely. For this reason alone it seems plausible, if not probable, that the payoff from offering multiple service classes will outweigh the cost of the extra mechanism."

**Structuring a design question:**
- *Base:* "Service Selection. The architecture assigns service classes to flows."
- *Shenker [conceptual]:* "Who Chooses the Service for a Flow? There are essentially two possible answers: the flow can pick the service, or the network can pick the service. We now contrast these two options."

**Reporting a measured result (note: results stay assertive):**
- *Base:* "Multiple nodes per zone reduce per-hop latency."
- *Shenker [systems]:* "Placing 4 nodes per zone reduces per-hop latency by about 45%. The point to take away is that overloading a zone has the same latency effect as reducing the number of nodes in the system. Of course, this comes at the cost of additional per-node state for tracking peers."

**Opening a HotNets position paper:**
- *Base:* "We propose a fault localization system for distributed applications. It works across layers and domains and is incrementally deployable."
- *Shenker [HotNets position]:* "When a user-visible fault occurs, the first step toward diagnosis is localization: determining where the fault occurred. Haven't we all been in videoconferences where someone freezes and everyone wonders if it's something at their end or elsewhere? This brings us to our position statement: *the Internet needs a universal fault localization primitive that is cross-layer, cross-domain, and cross-application.* Our goal is to stir up a debate about whether such a primitive is practical. Like the ECN bit, which is standardized while the logic that sets it is not, our primitive specifies the interface and deliberately leaves the policy open."

---

## When to apply, and the one hard carve-out

Apply this profile when the user asks for Shenker voice, or when the paper is a **networking/systems position paper, architectural proposal, vision paper, or systems-design paper** — and pick the matching register (R1). **HotNets provocations use the modern HotNets position register (group S, R58–R64) layered on the conceptual-register rules** — this is the closest fit for a present-day HotNets submission and the most relevant to current work; SIGCOMM/NSDI design papers use the systems register; CCR/whitepaper proposals use the proposal register; archival conceptual/position papers (JSAC-style) use the conceptual register with conversationality dialed down (R64).

**The one hard carve-out, in every register:** *measured results and evaluation numbers are asserted plainly, never hedged* (R19). The Shenker register governs design rationale, framing, and trade-off discussion; the base profile's flat assertiveness still governs every sentence that reports a number you measured. A drift into "our system seems to achieve roughly a 2× improvement" is off-voice in any Shenker register.

Do not apply this profile silently — it inverts real base rules. Default to `voice_profile.md` unless the register or the user's request calls for this one.

---

## §T. Arpit's storytelling overlay (R65–R70) — added 2026-06-30

From Arpit's reconciliation of a co-author pass on the SIGCSE Pramana intro (see
`reflections/arpit_storytelling_deconstruction_2026-06-30.md`). When writing in Arpit's voice using
the Shenker conceptual register, layer these ON TOP. They make the register warmer and more
reader-led than terse Shenker, and override two Shenker defaults (noted).

**R65. Discourse markers are narrative glue.** Keep sentence-opening signposts that mark the
argument's move ("However,", "More concretely,", "The catch is,", "Interestingly,", "Here,",
"What's worth noting is that"). This EXTENDS R21 (keep logical joints) and relaxes the anti-AI ban on
"notably/crucially" — strip a marker only when no logical move follows it.

**R66. Explicit, quotable thesis sentence echoing the title.** State the big idea once as a standalone
claim in the title's words ("This pedagogical transformation … requires facilitating experiential
learning"). Sharpens R4 (explicit purpose) and R58 (position statement) for Arpit's register.

**R67. Direct research-statement over gedanken (OVERRIDES R32/the "Suppose…" pivot).** Prefer "This
paper explores / shows / argues…" to a thought-experiment opener. The Gedanken template (R32) becomes
an OPTION, not the default, in Arpit's register.

**R68. i.e./e.g. parentheticals, freely** — gloss a term in the reader's words (i.e.) or name concrete
instances (e.g.) inline. Complements R38 (define-by-naming) and R39 (assert-then-gloss).

**R69. Deliberate repetition of the central term for cohesion** — repeating the title concept at each
structural beat is cohesion, not redundancy.

**R70. Run the precision sweep paper-wide** (the Layer-B class): hedge scan (R17 applied to EVERY
empirical universal, not just rationale), referent scan (named-over-vague extended to pronouns and
actors), conflation scan (thing-vs-process, abstract-vs-concrete), explicitness scan (explicit numbers
and named actors). Process: generalize a flag into a class; adopt-once-sweep-everywhere; a Codex
audit does not substitute for a domain-expert human pass on this class.

**Em-dash note:** Arpit's no-em-dash rule is NOT self-enforcing across co-author edits; re-apply it
after any collaborator pass (unless told to integrate those edits as-is).
