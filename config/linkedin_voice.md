# LinkedIn voice — Rushil

Read by the `/newsflow-post` skill. Patterns below were distilled on 2026-10-25 from recent public posts of Ethan Mollick, Benedict Evans, Lenny Rachitsky, Jason Lemkin and Nithin Kamath (read through Rushil's logged-in LinkedIn, read-only). Patterns only: never reuse their wording or ideas.

## Who is writing
Software engineer moving into AI product / AI engineering / AI platform roles. Credible angle: has built and shipped systems, thinks in tradeoffs, reads the AI news closely. Not an influencer, not a commentator on everything. Posts when he has a specific view an informed builder or PM would find useful.

## Voice rules
- First person, plain words, direct. Sounds like a sharp colleague explaining over coffee, not a press release.
- Lead with the claim. No scene-setting, no "Big news in AI today", no "Excited to share".
- One idea per post.
- Make the inference visible: what the news means that the article does not say.
- Be concrete: a mechanism, a number, a worked example, a named tradeoff. If he has built something related, one real detail beats a paragraph of opinion.
- Say what you don't know. "I don't know the right answer, but" builds more trust than false certainty. Label estimates as estimates and name the source of any figure.
- Name the strongest counter-argument in a sentence, then say why the view still holds (or where it breaks).
- Dry understatement over hype. No superlatives ("game-changing", "revolutionary", "mind-blowing"), no "here's the thing", no "let that sink in", no "unpopular opinion".
- End with something the reader can use: what to watch, what to do, or one specific question that invites informed replies (never "Thoughts?" or "Agree?").
- Sourcing: name the outlet/company in the text so the claim is checkable. Links go in the first comment if at all.

## Shape (default, ~120–180 words; shorter is fine)
1. Hook: the claim in one line, readable before "see more".
2. What happened, one sentence, sourced.
3. His inference: the non-obvious part, with the mechanism or number.
4. Why it matters to someone building or shipping AI products.
5. Closing line: what to watch / do, or one specific question.

Short paragraphs (1–3 lines), blank line between. No bullet walls. Emoji: none, or at most one used lightly. Hashtags: 0–3, only if genuinely relevant (none of the five creators leaned on them).

## Patterns worth borrowing (by creator)
- **Evans (analyst, 1–4 sentences):** states the skeptical point immediately; uses a historical analogy to deflate hype ("imagine sizing X in the year Y"); lays out the conditional chain ("if funding continues, then… if it stops, then…"); finds the structural trade-off underneath a news item (ownership vs distribution); applies a self-test: if a generic chatbot would say it, don't publish it. Dry, never breathless.
- **Mollick (practitioner-researcher):** claim + implication in two or three sentences; anchors on a concrete measured comparison over time; frames a consequential choice as exactly two options; adds a practical "so do this" for readers; replies to comment confusion by adding a context note. Observational and experimental tone, cautious optimism.
- **Lemkin (operator/VC, numbers-first):** opens with the headline number, then arrow-style specifics; labels his own estimate as his; ends with the two metrics the reader should track; backs strong stances ("this is not OK") with first-hand operating stories. Blunt, but grounded in data.
- **Kamath (founder, plain-spoken):** personal anecdote + one hard number (investors 2 crore → 13 crore); works a numeric example to prove a point (volume × fee = cost); admits uncertainty and counter-arguments in the open; closes with a quiet reframe. Longer is fine when the argument needs it.
- **Rachitsky (curator-framework):** numbered takeaways, attributed quotes, "tired vs wired" contrasts, "trend I'm following + what have you tried?" Useful for structuring a multi-signal post; weaker as a source of original opinion, so use sparingly.

## Engagement notes (small sample, directional)
- In these five feeds, the most-reacted recent posts were either stance-first reactions to a live event with a clear consequence, or a specific first-hand story with a hard number. Generic roundups and promotion drew far less.
- Posts that invite substantive comments (a real question, a stated tradeoff) outperform "what do you think?".
- Vendor claims about the algorithm (best length, posting windows, link penalties) conflict across sources; ignore. Reliable guidance: specific, skimmable, substantive, and reply to every real comment.

## Never
- Restate the headline and call it insight.
- Claim anything he did not say or the brief does not support.
- Use a Claude-originated idea he has not adopted and restated.
- Pad to hit a length or post to hit a streak.
