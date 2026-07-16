# Reddit Data API application draft

Copy-ready draft based on Reddit's forms and policies visible on 2026-07-16. Review current policy and replace every bracketed value before submission. Repository does not guarantee approval.

## Important classification

Select **Developer** for a private external application. Do not claim academic research or select Reddit for Researchers unless project meets that program's academic eligibility. Describe personal investment due diligence truthfully; do not hide AI-assisted processing.

## Subject of inquiry

```text
Data API access request for private read-only external content organizer
```

## Current use of Reddit data

```text
None through the API. The prototype is approval-gated and uses local fake responses for tests. I will not access Reddit data programmatically until Reddit explicitly approves this request and provides the applicable access information and limits.
```

## Purpose of product or service

```text
Investment Research OS is a private, non-commercial, single-user application that helps me organize public investment discussions for my own due diligence. Reddit is one input alongside official SEC filings, issuer announcements, and market data. The application is not a trading bot, does not execute trades, and is not offered to other users.
```

## What will you deliver to users/customers with Reddit data?

```text
The only user is me. The application will provide a private ticker workspace containing links to original Reddit discussions, extracted ticker and topic labels, recurring discussion narratives, conflicting claims, and research gaps. Reddit content will not be published, resold, licensed, or exposed to third parties as a user-facing dataset. I will review original source links before making any personal decision.
```

## Distribution and expected audience

```text
The application will run as a private external service and dashboard for one person. There is no public distribution, signup, advertising, subscription, client access, or commercial use. Source code and compliance documentation are public only so Reddit can inspect the implementation; the running dashboard and collected data remain private.
```

## Benefit/purpose for Redditors

```text
This V1 does not claim a direct community-facing benefit because it has one private user. Its purpose is to help me find and revisit relevant public investment discussions while preserving attribution and canonical links so I can read the original context on Reddit. It will not post, comment, vote, message, moderate, profile users, or otherwise alter anyone's Reddit experience.
```

## Detailed Bot/App behavior on Reddit

```text
Investment Research OS is an external, read-only application. After approval, it will authenticate with Reddit OAuth using a unique User-Agent and access only a small allowlist of public investment-related subreddits. At low scheduled frequency, it will request recent public posts and selected comment trees, within every limit Reddit assigns.

Deterministic code will deduplicate objects, identify possible stock ticker/company references, and preserve object IDs, timestamps, and canonical Reddit permalinks. It will not retain usernames or account IDs. The private dashboard will organize selected discussions by ticker, topic, claim, and source so I can perform personal due diligence against SEC filings, issuer announcements, and market data.

If Reddit approves this disclosed processing, selected post or comment text may be sent for one-time language-model classification or summarization. It will not be used to train or fine-tune any model. I will not enable this feature until I confirm Reddit's approval covers it and the selected provider offers appropriate no-training and retention controls. The application will not infer sensitive traits, re-identify users, match Reddit identities to off-platform identities, or create Redditor profiles.

The application will not submit posts or comments; vote; send messages; moderate; follow users; access private content; scrape Reddit; bypass access controls or rate limits; manipulate engagement; publicly repost Reddit content; sell or license Reddit data; or provide automated trading advice. Cached raw text will be minimized, limited to 48 hours unless Reddit approves another period, checked for removals, and deleted when source content is removed, access ends, or Reddit requires deletion.

The current public prototype implements only a bounded read-only fetch of recent post metadata. It makes no database writes and no AI calls.
```

## What is missing from Devvit?

```text
The primary product surface is a private external dashboard, not an app installed in a subreddit or an experience that posts or interacts on Reddit. Its core workflow combines approved Reddit discussions with SEC filings, issuer disclosures, market data, a relational evidence ledger, historical thesis versions, and private operator notes in infrastructure outside Reddit.

I found no standard Devvit deployment flow whose sole interface is this private external dashboard and whose purpose is to feed a broader off-Reddit evidence system. Devvit external-service integration also uses reviewed or limited-access capabilities. I am therefore requesting approval for the external Data API path rather than claiming Devvit lacks general functionality. If Reddit recommends a supported Devvit architecture for this exact approved scope, I am willing to adapt.
```

## Source code or platform URL

```text
https://github.com/[YOUR_GITHUB_USERNAME]/investment-research-os
```

Publish this repository, replace placeholder, then submit. Do not submit local filesystem path.

## Subreddits

Proposed initial allowlist:

```text
r/stocks
r/investing
r/ValueInvesting
r/BiotechStocks
r/pennystocks
```

Remove any community not needed. Smaller truthful scope improves review clarity. Do not add more until approved.

## Bot/App username

```text
N/A. The application is read-only and will not operate a posting or interaction account. OAuth will be associated with my Reddit account: [YOUR_REDDIT_USERNAME].
```

## Data budget

Reddit's form wording is ambiguous. Do not invent a number. Choose and submit one truthful statement:

```text
Personal non-commercial project. Expected load is low and will remain within the limit Reddit assigns. Budget for Reddit data access: USD [YOUR_MONTHLY_BUDGET] per month.
```

## Before submitting

- Replace GitHub and Reddit username placeholders.
- Decide truthful monthly data budget.
- Publish repository without `.env`, credentials, captures, or private notes.
- Confirm subreddit allowlist.
- Confirm model provider can meet disclosed no-training and retention controls; otherwise state inference will remain disabled.
- Read current Responsible Builder Policy, Data API Terms, Developer Terms, and request form again.
