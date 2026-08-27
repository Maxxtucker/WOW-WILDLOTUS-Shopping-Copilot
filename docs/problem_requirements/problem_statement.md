# Shopping Copilot: AI Conversational Search and Recommendations

> **Technical Workshop Webinar with Q&A**  
> **Date:** 28 Aug 2026  
> **Time:** 4:00 PM – 4:45 PM  
> **Webinar:** Click here to join the webinar!

## Table of Contents

- [1. Background](#1-background)
- [2. Problem Statement](#2-problem-statement)
  - [I. Core Architecture: Intent Routing & Hybrid Pipeline](#i-core-architecture-intent-routing--hybrid-pipeline)
  - [II. Dialog Strategy: Multi-Turn Scenario Evolution](#ii-dialog-strategy-multi-turn-scenario-evolution)
  - [III. Self-Evolution: Dynamic Context Programming](#iii-self-evolution-dynamic-context-programming)
  - [IV. Evaluation Matrix: Product & Efficiency Metrics](#iv-evaluation-matrix-product--efficiency-metrics)
- [3. Constraints & Scope](#3-constraints--scope)
- [4. Available Resources & Data](#4-available-resources--data)
- [5. Deliverables](#5-deliverables)
- [6. Judging Criteria](#6-judging-criteria)

---

## 1. Background

Traditional e-commerce search engines heavily rely on static keyword matching, failing to capture the fluid shifts of genuine consumer psychology and the distinction between open-ended browsing and high-intent buying.

In modern conversational commerce, constructing an intelligent agent that leverages **Dynamic Context Programming** is critical to bridging the gap between ambiguous user queries and complex product catalogs.

Solving this challenge directly impacts core industrial metrics such as:

- Retrieval coverage
- Recommendation precision
- Conversion efficiency
- User interaction cost
- Personalization quality

---

## 2. Problem Statement

Participants are challenged to architect an intelligent, next-generation shopping agent capable of navigating real-world customer dynamics.

Moving beyond rigid search filters, the engineered system must demonstrate:

- Deep cognitive understanding
- Runtime architectural agility
- Commercial efficiency
- Robust multi-turn reasoning
- Effective product retrieval and ranking

The system should be built upon the following four core pillars.

### I. Core Architecture: Intent Routing & Hybrid Pipeline

#### Dual-Track Routing

The system should instantly detect the user's underlying intent and route the request into one of two tracks:

**Buying Track**

For high-intent users with explicit purchase requirements:

- Trigger a high-precision filtering pipeline.
- Extract and lock hard constraints.
- Prioritize exact attribute matching.
- Reduce irrelevant candidate products aggressively.

**Browsing Track**

For open-ended or exploratory users:

- Trigger diverse dense retrieval.
- Allow cross-category and scenario-based matching.
- Prioritize semantic relevance and discovery.
- Preserve diversity in the candidate pool.

#### Pipeline Base

Construct an entirely in-memory retrieval and ranking pipeline:

```text
User Query
   ↓
Intent Router
   ↓
Multi-Route Retrieval
   ├── Keyword Retrieval
   ├── Category Retrieval
   └── Vector / Dense Retrieval
   ↓
Candidate Fusion / Dynamic Truncation
   ↓
LLM Semantic Ranking
   ↓
Top-K Recommendations
```

The retrieval stage should combine:

- Keyword similarity
- Category matching
- Vector similarity
- Dynamic retrieval weights
- Context-aware truncation

The final candidates should then be ranked using an LLM or another semantic scoring mechanism.

---

### II. Dialog Strategy: Multi-Turn Scenario Evolution

#### Dynamic State Machine

Build a robust conversational state tracker capable of handling evolving user requirements across multiple turns.

The system should support:

**Information Accumulation**

Incrementally collect and preserve useful shopping constraints such as:

- Product category
- Price range
- Size
- Color
- Brand
- Material
- Occasion
- Style
- Intended user
- Other product attributes

Example:

```text
Turn 1: "I need shoes."
Turn 2: "For running."
Turn 3: "Under $100."
Turn 4: "Prefer lightweight ones."
```

The agent should accumulate these constraints instead of treating each message independently.

**Intent Override**

The system must also detect abrupt changes in user intent and correctly erase, replace, or rewrite outdated state.

Example:

```text
Turn 1: "I want black running shoes under $100."
Turn 2: "Actually, forget running shoes. I need formal shoes."
```

The previous `running` constraint should no longer control retrieval.

#### Proactive Guidance

When the user query is overly general and creates an excessively large candidate pool, the system should trigger an **immediate retrieval cutoff** instead of performing wasteful retrieval and ranking.

The agent should then proactively ask structured clarification questions that reduce the search space.

Example:

```text
User: "I want some clothes."

Agent:
"What are you mainly looking for?
1. Tops
2. Pants
3. Jackets
4. Dresses
5. Shoes"
```

The objective is to guide the user toward the correct product using as few conversational turns as possible.

---

### III. Self-Evolution: Dynamic Context Programming

#### Runtime Adaptation

Use accumulated dialog history to perform **Personalized Context Distillation**.

The system should continuously update two layers of contextual information:

**Short-Term Session State**

Stores information relevant to the current shopping session, such as:

- Current intent
- Active constraints
- Rejected preferences
- Recently viewed candidates
- Current category
- Current retrieval strategy

**Long-Term User Profile**

Stores reusable preferences distilled from previous interactions, such as:

- Preferred styles
- Typical price range
- Favorite categories
- Brand preferences
- Common sizes
- Frequently rejected attributes

The goal is to compress raw conversation history into compact, useful context rather than repeatedly passing the entire conversation into downstream components.

#### Adaptive Orchestration

Use **Dynamic Context Programming** to modify the runtime workflow according to the evolving state of the conversation.

The agent may dynamically adapt:

- Intent-routing strategy
- Retrieval route selection
- Retrieval weights
- Candidate pool size
- Slot importance
- Slot decay
- Clarification strategy
- Ranking prompts
- Ranking features
- Recommendation diversity
- Search termination conditions

Instead of following a fixed pipeline, the agent should iteratively refine its own guidance and retrieval logic based on user behavior and accumulated context.

---

### IV. Evaluation Matrix: Product & Efficiency Metrics

Evaluation is anchored on the **final purchased product record** contained in the Amazon dataset.

Performance is measured across three primary dimensions.

#### Coverage — Hit Rate@K

Measures whether the correct purchased item is successfully retrieved within the candidate set.

A higher Hit Rate@K indicates stronger catalog recall and better retrieval boundary coverage.

#### Precision — MRR / Top-K Hit Rate

Measures how highly the final purchased item appears in the recommendation ranking.

**Mean Reciprocal Rank (MRR)** is defined as:

\[
MRR = \frac{1}{N}\sum_{i=1}^{N}\frac{1}{rank_i}
\]

where \(rank_i\) is the position of the correct product for session \(i\).

The objective is not only to retrieve the correct item, but to push it as close as possible to rank #1.

#### Efficiency — MTTC

**MTTC (Mean Turns to Conversion)** measures how many interaction turns are required before the system successfully converges on the correct product.

The evaluation heavily rewards systems that:

- Reach the correct recommendation quickly.
- Ask useful clarification questions.
- Avoid redundant dialog.
- Minimize unnecessary cognitive load.

The session has a hard maximum of **10 turns**.

---

## 3. Constraints & Scope

### In Scope

| Area | Details |
|---|---|
| Intent Detection | Designing highly sensitive intent-detection modules to split traffic into **Buying** and **Browsing** tracks |
| Retrieval | Implementing heterogeneous retrieval routing, dynamic weights, custom truncation, and slot decay |
| Memory | Engineering runtime-adaptive memory layers for personalized context distillation |
| Ranking | Fine-tuning prompt strategies or local scoring logic for the LLM ranking stage |
| Dialog | Building multi-turn state tracking, clarification logic, and intent override handling |
| Optimization | Compressing decision paths to improve ranking quality and reduce MTTC |

### Out of Scope

| Area | Restriction |
|---|---|
| UI/UX | UI/UX development is not evaluated; evaluation uses automated backend APIs and headless pipelines |
| Foundation Model Training | Training or full-parameter fine-tuning of base foundational LLMs is not required |
| External Vector Databases | Heavy external industrial vector DB clusters are prohibited; the system must run in-memory |
| Multimodal Processing | The task is restricted to text catalogs, structured metadata, and text dialogs |

### Limits

| Constraint | Requirement |
|---|---|
| Maximum Turns | Hard limit of **10 turns per session** |
| Turn Limit Penalty | Forced termination and zero score if the limit is exceeded |
| Catalog Mutation | The Amazon product dataset is strictly read-only |
| Product Injection | Mock ASIN or structural catalog injections are not allowed |

### Allowed Assumptions

- Inputs are pre-cleaned text strings.
- No spelling correction, typo handling, or ASR noise processing is required.
- Product catalog, pricing, and category trees remain static during the hackathon.
- Each session represents one isolated user interaction.
- Multi-user concurrency stress testing is not required.

---

## 4. Available Resources & Data

Participants receive a frozen and reproducible competition kit derived from the **Amazon Reviews 2023** dataset.

### Competition Data

The provided competition package contains:

- **50,000 products** from the Amazon Reviews 2023 `Clothing_Shoes_and_Jewelry` category.
- **200 labeled public development sessions** for local testing and iteration.
- **800 private evaluation sessions** retained by the organizer.
- Separate users and target products for public and private evaluation sessions.

### Participant Resources

The organizer provides:

- A weak **BM25 starter Agent** implemented in Python.
- A deterministic local evaluator for:
  - Hit Rate@10
  - MRR
  - MTTC
  - Efficiency
  - Combined `TechnicalScore`
- A published Python Agent interface.
- A machine-readable API contract.
- Evaluation configuration.
- Reproducible baseline results.
- Data documentation.
- Submission rules.
- A SHA256 checksum file for verifying the downloaded catalog.

Participants may modify or completely replace the starter Agent while continuing to use the official evaluator.

Supported approaches include:

- Keyword retrieval
- Rule-based methods
- Dense retrieval
- Hybrid retrieval
- Reranking
- Local models
- External model APIs

A paid LLM is **not required** to complete the challenge.

Teams that choose to use external services are responsible for:

- Their own credentials
- API usage limits
- Service costs
- Keeping secrets out of public repositories

### Resources

- **Participant Repository:**  
  https://github.com/TechJam2026/techjam-conversational-search

- **Participant Kit Release:**  
  https://github.com/TechJam2026/techjam-conversational-search/releases/tag/participant-kit

- **Original Amazon Reviews 2023 Dataset:**  
  https://amazon-reviews-2023.github.io/

> The competition catalog and evaluation sessions are prepared and frozen by the organizer. Participants do not need to download or reconstruct the full upstream Amazon Reviews 2023 dataset.

---

## 5. Deliverables

### 1. Written Project Description — Devpost

Submit a clear written description containing:

- How the solution addresses the problem statement.
- Development tools used, for example:
  - VS Code
  - Google Colab
  - Jupyter Notebook
- APIs used, for example:
  - OpenAI GPT-4o
  - Google Maps API
- Libraries and frameworks used, for example:
  - Hugging Face Transformers
  - PyTorch
  - scikit-learn
  - pandas
- Datasets and assets used, for example:
  - Google Local Reviews
  - Manually labeled data

### 2. Public Code / GitHub Repository

Submit a public GitHub repository containing:

- Well-structured and commented code covering all major system components.
- A `README.md` containing:
  - Project overview
  - Setup and installation instructions
  - Steps to reproduce results
  - A brief reflection on limitations
  - Improvements that would be made with additional time
  - Team member contributions, if applicable

### 3. Demo Video

Submit a short video that:

- Demonstrates the solution working end-to-end.
- Shows relevant inference results, API usage, or result analysis.
- Is uploaded to YouTube.
- Is publicly accessible.
- Is linked in the Devpost description.
- Does not contain unauthorized third-party trademarks or copyrighted content.

> For backend or NLP tracks, a front-end interface is not required. A walkthrough showing API usage, inference examples, terminal output, or evaluation results is acceptable.

---

## 6. Judging Criteria

| Judging Criteria | Definition | Weight |
|---|---|---:|
| **Technical Execution** | Demonstrates strong engineering fundamentals, including well-structured code, thoughtful architecture, effective model/API usage, reliable execution, and deliberate technical complexity | **35%** |
| **Innovation & Problem Insight** | Demonstrates originality in both idea and approach, with a clear understanding of the challenge and a solution that directly addresses the core problem | **20%** |
| **Impact & Relevance** | Shows potential to deliver meaningful value to real users or stakeholders beyond the hackathon setting | **20%** |
| **Feasibility & Practicality** | Uses a technically and operationally realistic architecture with proportionate resource usage and practical implementation choices | **15%** |
| **Presentation & Communication** | Final-event presentation clearly communicates the problem, solution, impact, and technical reasoning, with strong responses during Q&A | **10%** |

---

## Summary

The goal of this track is to build an intelligent conversational shopping agent that does more than retrieve products from keywords.

A strong solution should combine:

```text
Intent Understanding
        ↓
Dynamic State Tracking
        ↓
Adaptive Retrieval Routing
        ↓
Hybrid Candidate Retrieval
        ↓
Semantic Reranking
        ↓
Proactive Clarification
        ↓
Context Distillation
        ↓
Runtime Strategy Adaptation
        ↓
Fast Conversion
```

The final system should optimize both **recommendation quality** and **interaction efficiency**, successfully identifying the user's target product while minimizing unnecessary turns.
