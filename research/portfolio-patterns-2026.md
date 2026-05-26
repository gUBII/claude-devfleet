# Engineering Portfolio Patterns — 2026 Research Report

**Audience:** Orchestrator informing a refresh of `4han.life` (`v2/employer/index.html`)
**Owner profile:** Solo engineer, multi-project shipper (Claude DevFleet, Nexis365, portfolio infra), targeting US/AU mid-senior engineering recruiters with <30s skim windows.
**Scope note:** Recommendations are pattern-level. The current `v2/employer/index.html` was *not* directly inspected this session (WebFetch/Bash were denied in subagent). Pair this report with a fresh diff of current copy before dispatching the refresh agent.

---

## Executive Summary

In 2026, engineering portfolios are being read in ~11 seconds by recruiters whose eyes lock onto the top third of the page ([InterviewPal](https://www.interviewpal.com/blog/how-long-recruiters-actually-spend-reading-your-resume-data-study), [ResumeHeatMap](https://resumeheatmap.com/eye-tracking-study)). The dominant layout is the bento grid — adopted by Linear, Vercel, Raycast, and Cursor — and tied to a +31% time-on-page lift on SaaS surfaces ([Landdding](https://landdding.com/blog/blog-bento-grid-design-guide), [StudioMeyer](https://studiomeyer.io/en/blog/bento-grid-layouts)). The most credible AI-era framing is "agentic engineering" — judgment + orchestration over LLM output — and is now used as the explicit foil to "vibe coding" ([Voitanos](https://www.voitanos.io/blog/vibe-coding-vs-agentic-engineering/), [Stack Overflow](https://stackoverflow.blog/2026/05/18/what-the-ai-hype-gets-wrong)). Recruiters discount static stats, generic hero copy, 40-item tech-soup, and dead deploy links; they reward live demos, ≤2-min Loom walkthroughs, contribution heatmaps, and project tiles structured Problem → Approach → Architecture → Result ([Tandam](https://tandamconnect.com/blog/ai-agent-portfolio-examples-2026), [Arslan DG](https://arslandg.substack.com/p/3-portfolio-projects-that-actually)). For a multi-project solo shipper, the strongest narrative shape is a hybrid: a single editorial spine ("I orchestrate agents to ship faster than headcount allows") laid across a bento of live, dated tiles.

---

## Sub-Q1 — Hero / Above-the-Fold Patterns That Work in 2025–2026

**Lead pattern: bento grid + named-narrative hero.** Bento adoption hit 67% of top ProductHunt SaaS launches in 2026 ([Landdding](https://landdding.com/blog/bento-grid-design-by-website-category-where-the-pattern-wins)), with Linear, Vercel, Raycast, and Cursor anchoring the canonical look. SaaSFrame's 2026 guide attributes the lift to *parallel features being legible without sequential scroll* — which maps directly onto a multi-project solo engineer ([SaaSFrame](https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide)).

**Patterns that are *working* in 2026:**

- **"Currently shipping" / now-block above the fold.** Live demos and current-work blocks signal authenticity and freshness; portfolios that lead with active work get higher dwell ([Lovable](https://lovable.dev/guides/student-portfolio-examples), [DEV Anthology](https://dev.to/nk2552003/the-anthology-of-a-creative-developer-a-2026-portfolio-56jp)).
- **Editorial typography hero.** Awwwards-featured engineer portfolios in 2025–2026 lean on scale-contrast type, draw animations, and animated wordmarks over hero illustrations ([Awwwards — Bastian Gasser](https://www.awwwards.com/inspiration/hero-section-bastian-gasser-portfolio), [Awwwards — animated typography](https://www.awwwards.com/inspiration/animated-typography-portfolio)).
- **Three-tier hook.** Headline → pitch → context — explicitly cited by SiteBuilderReport's 2026 engineer portfolio teardown as the structure that converts ([SiteBuilderReport](https://www.sitebuilderreport.com/inspiration/engineer-portfolios)).
- **Bento with mixed tile shapes.** Stats tile + project tile + live-status tile + writing tile in one composition reads as "real human shipping things" rather than templated grid ([Mockuuups](https://mockuuups.studio/blog/post/best-bento-grid-design-examples/)).

**Patterns that are *not* working:**

- Full-screen three.js / particle hero with no content above the fold ([RemoteWorks](https://remoteworks.pro/blog/best-web-developer-portfolio-examples), [Hakia](https://hakia.com/skills/building-portfolio/)).
- Centered "Hi, I'm X. I build cool stuff." hero with one gradient blob and a CTA — explicitly called out as default-template aesthetic ([SaaSFrame](https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide)).

---

## Sub-Q2 — How AI-Era Engineers Are Framing Their Work in 2026 (Authentic vs Cringe)

The cleanest authenticity axis in 2026 is **"agentic engineer" vs "vibe coder."** Voitanos frames the split explicitly: agentic engineering keeps human judgment in the driver's seat while delegating tedium to agents; vibe coding hands the keys to the LLM ([Voitanos](https://www.voitanos.io/blog/vibe-coding-vs-agentic-engineering/)). Stack Overflow's May 2026 piece reinforces that "you can't vibe code scale" — and that the engineers being hired are the ones who can demonstrate orchestration, evaluation, and accountability ([Stack Overflow](https://stackoverflow.blog/2026/05/18/what-the-ai-hype-gets-wrong)).

**Reads authentic in 2026:**

- Concrete artifacts: "Built a multi-agent dispatcher that runs 3 isolated worktrees in parallel; here's the repo and a 90-second Loom of it shipping a PR."
- Action verbs with measurable outcome: "Deployed CrewAI-based research agent — saved 20 hrs/week" ([Tandam](https://tandamconnect.com/blog/ai-agent-portfolio-examples-2026)).
- Naming the *judgment* layer: what the human decides, evaluates, governs — not just what the agent typed ([CIO](https://www.cio.com/article/4166029/the-570k-canary-what-ai-coding-agents-reveal-about-enterprise-ais-real-gaps.html)).
- Showing tool integration (MCP, function calling, tool-discovery flow) over claiming capability ([Tandam](https://tandamconnect.com/blog/ai-agent-portfolio-examples-2026)).

**Reads cringe in 2026:**

- "10x engineer," "AI-native," "passionate about clean code," "I love solving problems" — generic developer clichés that recruiters explicitly skim past ([RemoteWorks](https://remoteworks.pro/blog/best-web-developer-portfolio-examples), [Compass Calendar](https://newsletter.compasscalendar.com/p/77-things-to-avoid-in-2026-developer)).
- "Vibe coder" used as self-description with no engineering substance attached ([explainx.ai](https://explainx.ai/blog/agentic-fatigue-vibe-coding-ai-developer-productivity-paradox)).
- Buzzword stacking: "AI-native agentic LLM-powered RAG-first multi-agent orchestrator engineer" — reads as someone who hasn't actually shipped.

**Language that lands:** "I orchestrate agents to ship faster than headcount allows" → followed by a *live counter* of shipped work. Tell-then-show.

---

## Sub-Q3 — Proof-of-Work Signals Recruiters Value Most in 2026

**Hard data on scan behavior:**

- Average initial portfolio scan: **11.2 seconds** (4,289 reviews, 312 recruiters, Aug 2025) ([InterviewPal](https://www.interviewpal.com/blog/how-long-recruiters-actually-spend-reading-your-resume-data-study)).
- 94% of recruiters complete the initial scan in <10 seconds; rejections average 5.2 seconds ([ResumeHeatMap](https://resumeheatmap.com/eye-tracking-study)).
- 80% of viewing time concentrates in the **top third** of the page ([HR Dive](https://www.hrdive.com/news/eye-tracking-study-shows-recruiters-look-at-resumes-for-7-seconds/541582/)).
- Vague bullets get 0.9s; specific quantified bullets get 2.1s ([ResumeHeatMap](https://resumeheatmap.com/eye-tracking-study)).
- 60%+ of recruiters now review portfolios on mobile ([WhatIsTheSalary](https://whatisthesalary.com/guides/software-engineer-portfolio/)).

**Signals that move the needle (ranked by recurrence across sources):**

1. **Live deployed demo** that survives a click — dead Heroku/Vercel links are the most-cited red flag ([Compass Calendar](https://newsletter.compasscalendar.com/p/77-things-to-avoid-in-2026-developer), [Arslan DG](https://arslandg.substack.com/p/3-portfolio-projects-that-actually)).
2. **Loom / 90-sec walkthrough** of agent or system in action ([Tandam](https://tandamconnect.com/blog/ai-agent-portfolio-examples-2026), [Entri](https://entri.app/blog/how-to-build-an-ethical-hacker-portfolio/)).
3. **GitHub contribution heatmap** — described as "one of the most powerful signals" by 2026 AI-engineer hiring writeups ([Tandam](https://tandamconnect.com/blog/ai-agent-portfolio-examples-2026)).
4. **Quantified outcome on each project tile** — saved X hours, shipped Y PRs, reduced Z latency.
5. **Architecture diagram or system explainer** alongside the repo link ([Pipeline2Insights](https://pipeline2insights.substack.com/p/how-to-create-data-engineering-data-engineers-github-portfolio-in-2026)).
6. **Public revenue / usage transparency** for indie work — strong signal in build-in-public circles ([Indie Hackers](https://www.indiehackers.com/post/tech/hitting-a-5-figure-mrr-with-an-open-source-portfolio-ehAiGujGzBkd4BhnPoIS)).
7. **Tight tech list (12–15 items)** vs kitchen-sink 40 ([Compass Calendar](https://newsletter.compasscalendar.com/p/77-things-to-avoid-in-2026-developer)).

Stack Overflow Developer Survey 2024 (cited downstream) puts active-portfolio engineers at 65% higher callback rate ([WhatIsTheSalary](https://whatisthesalary.com/guides/software-engineer-portfolio/)). Over 70% of tech recruiters review portfolios pre-interview ([Pesto](https://pesto.tech/resources/what-recruiters-look-for-in-developer-portfolios)).

---

## Sub-Q4 — 2024-Era Patterns That Now Read Stale / Template-y

Distilled from multiple 2026 teardowns ([Compass Calendar](https://newsletter.compasscalendar.com/p/77-things-to-avoid-in-2026-developer), [Muzli](https://muz.li/blog/portfolio-mistakes-designers-still-make-in-2026/), [RemoteWorks](https://remoteworks.pro/blog/best-web-developer-portfolio-examples), [SaaSFrame](https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide)):

**Copy clichés (kill these):**

- "Passionate about clean code"
- "10x engineer" / "rockstar" / "ninja"
- "I love solving problems"
- "Building the future of X"
- Static velocity claims with no date anchor ("16 PRs in 4 days" with no link, no timestamp, no repo)

**Design patterns now reading stale:**

- Centered hero with single gradient blob + one CTA
- Default three.js cube / particle field with no narrative
- Uniform card grid with identical padding, radius, shadow — no hierarchy
- "Skills" cloud of 40 logos including things touched once
- Animated typewriter intro ("I'm a [developer/designer/founder]…")
- Dark mode for its own sake when the brand doesn't justify it

**Structural staleness:**

- Project tiles with no live link, no repo, no metric — just a screenshot and a tech stack list
- Dead deploy links (Heroku free-tier sunset cleanup never happened)
- About page longer than the projects page
- No "last updated" / no timestamp anywhere — reads as abandoned

---

## Sub-Q5 — Story Arc vs Project Grid (and What the Data Actually Says)

**Honest caveat:** Hard dwell-time numbers comparing "story arc" vs "project grid" portfolios specifically are *thin*. The signal is qualitative and indirect.

**What the sources actually say:**

- Bento-layout SaaS pages: **+31% time-on-page** vs traditional stacked sections ([Landdding](https://landdding.com/blog/blog-bento-grid-design-guide)). This is the closest hard number.
- DEV's "experience-first portfolio" teardown argues for narrative spine over project grid, with anecdotal interview-conversion lift but no controlled data ([DEV — experience-first](https://dev.to/mohsinalipro/experience-first-portfolio-a-new-approach-to-showcasing-engineering-skills-22dd)).
- Arc.dev's hiring guide explicitly recommends a hybrid: narrative arc *through* a curated project set, not either/or ([Arc.dev](https://arc.dev/talent-blog/software-engineer-portfolio/)).
- Scale.jobs' portfolio storytelling analysis: narrative-arc portfolios kept reviewers scrolling long enough to recognize signature style; grid portfolios got bounced ([Scale.jobs](https://scale.jobs/blog/top-portfolio-storytelling-examples)).

**For a multi-project solo shipper specifically:** Pure narrative-arc penalizes you (you ship in parallel; a linear story doesn't fit). Pure grid penalizes you too (looks like a junior dev's CRUD-app gallery). The hybrid wins: **one editorial spine sentence above the fold + bento of dated, live-linked tiles below.**

---

## Direct Recommendations for `4han.life`

Pattern-level. Hand these to the dispatch agent alongside a fresh read of the current `v2/employer/index.html`.

1. **Replace static velocity claims with a live, dated counter.** "16 PRs in 4 days" reads as a stale boast the moment it ages. Wire a small GitHub-API-backed widget that shows rolling 30-day PRs / commits / projects-touched. Always-fresh, never stale. Use [github-readme-stats](https://github.com/anuraghazra/github-readme-stats)-style data or a custom Cloudflare Worker.

2. **Lead with a "currently shipping" block above the fold.** Hero spine: one editorial sentence ("I orchestrate Claude agents to ship across more projects than headcount allows"). Directly below: 2–3 dated cards — *DevFleet — shipping this week*, *Nexis365 — in production with [N] clinics*, *4han.life — you're on it*. Pattern source: [Lovable](https://lovable.dev/guides/student-portfolio-examples), [DEV Anthology](https://dev.to/nk2552003/the-anthology-of-a-creative-developer-a-2026-portfolio-56jp).

3. **Reframe DevFleet as agentic engineering, not "AI orchestrator."** Use substance language: "Multi-agent dispatch platform — isolated worktrees, MCP tooling, dependency-aware scheduling. Built it because I needed it." Avoid: "AI-native," "vibe coding," "the future of engineering." Anchor: [Voitanos](https://www.voitanos.io/blog/vibe-coding-vs-agentic-engineering/).

4. **Restructure each project tile: Problem → Approach → Architecture → Result + live link + repo + ≤2-min Loom.** This is the explicit 2026 AI-engineer portfolio canonical structure ([Tandam](https://tandamconnect.com/blog/ai-agent-portfolio-examples-2026)). Every tile gets a live URL, a repo URL, and a Loom — no exceptions.

5. **Adopt a bento grid for the project section.** Mixed tile sizes — DevFleet gets the hero-size tile, Nexis365 gets a tall tile with the rostering visual, smaller tiles for portfolio/experiments/writing. Aligns with Linear / Vercel / Raycast ([SaaSFrame](https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide), [Landdding](https://landdding.com/blog/blog-bento-grid-design-guide)).

6. **Cap the tech list at 12–15.** Cull anything not touched in the last 12 months. The cull itself signals taste ([Compass Calendar](https://newsletter.compasscalendar.com/p/77-things-to-avoid-in-2026-developer)).

7. **Audit and kill dead links.** Every deploy link in the current portfolio gets clicked; anything 404 / sleeping / Heroku-sunsetted gets removed or replaced with a self-hosted snapshot. Single biggest credibility leak in 2026 ([Arslan DG](https://arslandg.substack.com/p/3-portfolio-projects-that-actually)).

8. **Mobile-first review pass.** 60%+ of recruiters open portfolios on phones; verify the bento collapses cleanly, the hero spine reads in one thumb-scroll, and the live counter doesn't break ([WhatIsTheSalary](https://whatisthesalary.com/guides/software-engineer-portfolio/)). Test at 320 / 375 / 768 widths per `~/.claude/rules/web/testing.md`.

---

## Sources

- [SiteBuilderReport — Engineer Portfolios 2026](https://www.sitebuilderreport.com/inspiration/engineer-portfolios) — 20+ teardown of working engineer portfolio patterns.
- [SiteBuilderReport — Software Engineer Portfolios 2026](https://www.sitebuilderreport.com/inspiration/software-engineer-portfolios) — Companion gallery focused on SWE-specific patterns.
- [DEV — The Anthology of a Creative Developer 2026](https://dev.to/nk2552003/the-anthology-of-a-creative-developer-a-2026-portfolio-56jp) — Narrative-portfolio case study; explicitly rejects Hero-About-Projects template.
- [Lovable — 12 Portfolio Examples 2026](https://lovable.dev/guides/student-portfolio-examples) — Three-trait synthesis: process, strongest-first, respect time.
- [DEV — Indispensable Developer Portfolio 2026](https://dev.to/alfredo_aguilac1/the-indispensable-developer-portfolio-354n) — AI-era portfolio framing essentials.
- [DEV — Junior Dev Resume & Portfolio in the Age of AI](https://dev.to/dhruvjoshi9/junior-dev-resume-portfolio-in-the-age-of-ai-what-recruiters-care-about-in-2025-26c7) — Recruiter expectations re: AI tooling.
- [Pesto — What Recruiters Look For in Developer Portfolios](https://pesto.tech/resources/what-recruiters-look-for-in-developer-portfolios) — 70%+ recruiter pre-interview portfolio review stat.
- [Arc.dev — Software Engineer Portfolio Guide](https://arc.dev/talent-blog/software-engineer-portfolio/) — Hybrid narrative + curated project recommendation.
- [DEV — Experience-First Portfolio](https://dev.to/mohsinalipro/experience-first-portfolio-a-new-approach-to-showcasing-engineering-skills-22dd) — Argues for expertise pillars over project grid.
- [Scale.jobs — Top Portfolio Storytelling Examples](https://scale.jobs/blog/top-portfolio-storytelling-examples) — Narrative-arc portfolios outperform on dwell.
- [Arslan DG — 3 Portfolio Projects That Actually Impress 2026](https://arslandg.substack.com/p/3-portfolio-projects-that-actually) — Dead-link / tutorial-follower red flags.
- [Compass Calendar — 77 Things To Avoid 2026: Developer Edition](https://newsletter.compasscalendar.com/p/77-things-to-avoid-in-2026-developer) — Cliché and template-pattern hit list.
- [RemoteWorks — Best Web Developer Portfolio Examples 2026](https://remoteworks.pro/blog/best-web-developer-portfolio-examples) — Anti-three.js / anti-particle stance with reasoning.
- [Muzli — Portfolio Mistakes Designers Still Make in 2026](https://muz.li/blog/portfolio-mistakes-designers-still-make-in-2026/) — Generic design clichés to avoid.
- [Landdding — Bento Grid Design Guide 2026](https://landdding.com/blog/blog-bento-grid-design-guide) — 67% adoption among ProductHunt top 100; SaaS use cases.
- [Landdding — Bento Grid by Website Category Breakdown](https://landdding.com/blog/bento-grid-design-by-website-category-where-the-pattern-wins) — Where bento wins vs loses by surface type.
- [StudioMeyer — Bento Grid Layouts 2026](https://studiomeyer.io/en/blog/bento-grid-layouts) — Apple/Google bento canonical examples with code.
- [SaaSFrame — Designing Bento Grids That Actually Work](https://www.saasframe.io/blog/designing-bento-grids-that-actually-work-a-2026-practical-guide) — +31% time-on-page lift datapoint; Linear/Vercel/Raycast/Cursor as anchors.
- [Mockuuups — Best Bento Grid Design Examples 2026](https://mockuuups.studio/blog/post/best-bento-grid-design-examples/) — Mixed-tile-shape composition examples.
- [Awwwards — Bastian Gasser Portfolio Hero](https://www.awwwards.com/inspiration/hero-section-bastian-gasser-portfolio) — Editorial-typography hero exemplar.
- [Awwwards — Animated Typography Portfolios](https://www.awwwards.com/inspiration/animated-typography-portfolio) — Type-as-hero trend confirmation.
- [Voitanos — Vibe Coding vs Agentic Engineering](https://www.voitanos.io/blog/vibe-coding-vs-agentic-engineering/) — Core authenticity frame for the AI-engineer label.
- [Stack Overflow Blog — You Can't Vibe Code Scale](https://stackoverflow.blog/2026/05/18/what-the-ai-hype-gets-wrong) — May 2026 piece on substance vs hype in AI engineering roles.
- [CIO — $570K Canary on AI Coding Agents](https://www.cio.com/article/4166029/the-570k-canary-what-ai-coding-agents-reveal-about-enterprise-ais-real-gaps.html) — Enterprise framing of judgment/orchestration as paid skill.
- [Tandam — AI Agent Portfolio Examples 2026](https://tandamconnect.com/blog/ai-agent-portfolio-examples-2026) — Problem→Approach→Architecture→Result template; Loom + heatmap signals.
- [InterviewPal — 11.2 Second Scan Study](https://www.interviewpal.com/blog/how-long-recruiters-actually-spend-reading-your-resume-data-study) — Aug 2025 n=4289 study updating the 6-second myth.
- [ResumeHeatMap — 6 Fixation Points Study 2026](https://resumeheatmap.com/eye-tracking-study) — 80% attention in top third; specific vs vague bullet dwell.
- [HR Dive — 7 Second Eye Tracking Study](https://www.hrdive.com/news/eye-tracking-study-shows-recruiters-look-at-resumes-for-7-seconds/541582/) — Foundational eye-tracking dataset.
- [WhatIsTheSalary — Software Engineer Portfolio Guide 2026](https://whatisthesalary.com/guides/software-engineer-portfolio/) — 60%+ mobile review; 65% callback uplift datapoint.
- [Pipeline2Insights — Data Engineer GitHub Portfolio 2026](https://pipeline2insights.substack.com/p/how-to-create-data-engineering-data-engineers-github-portfolio-in-2026) — Architecture-diagrams-as-signal source.
- [Indie Hackers — 5-Figure MRR Open Source Portfolio](https://www.indiehackers.com/post/tech/hitting-a-5-figure-mrr-with-an-open-source-portfolio-ehAiGujGzBkd4BhnPoIS) — Build-in-public transparency as proof signal.
- [explainx.ai — Agentic Fatigue Meets Vibe Coding 2026](https://explainx.ai/blog/agentic-fatigue-vibe-coding-ai-developer-productivity-paradox) — Buzzword-saturation backlash signal.
- [github-readme-stats](https://github.com/anuraghazra/github-readme-stats) — Reference implementation for the live counter recommendation.
