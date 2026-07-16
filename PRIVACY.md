# Privacy notice

Last updated: 2026-07-16

Investment Research OS is an early, private, single-user prototype. It has no public users and is not affiliated with or endorsed by Reddit.

## Data accessed

After Reddit grants explicit API approval, the application may access public posts and comments from a small allowlist of investment-related subreddits through Reddit OAuth. It does not access private messages, private communities, saved items, votes, or other private account data.

The current prototype retrieves limited post metadata and, only when explicitly requested, post body text. It omits author identity, prints results to standard output, and does not persist them.

## Planned use

Approved Reddit data may be used to organize public discussions by company, ticker, topic, and cited evidence for one person's private due diligence. The application will preserve links to original Reddit content and will not publicly redistribute that content.

No Reddit content will be used to train a machine-learning model. No feature will infer sensitive traits, re-identify people, match Reddit identities to off-platform identities, or build profiles of Redditors.

AI-assisted classification or summarization will remain disabled unless Reddit approves that disclosed use and the selected processor provides suitable no-training and retention controls.

## Retention and deletion

Current prototype retains no Reddit content. Planned persistence must follow these controls:

- retain only fields needed for the approved purpose;
- keep raw post and comment text for no more than 48 hours unless Reddit explicitly approves another period;
- regularly re-check stored references and remove cached text when source content is removed or deleted;
- delete cached Reddit content and derived records when access ends or Reddit requires deletion;
- never place Reddit content in application logs or this repository.

## Sharing

Reddit data is not sold, licensed, or shared with other users. Any future subprocessors used for approved inference or hosting will be documented here before use.

Questions can be raised through this repository's issue tracker. Do not include private or sensitive information in an issue.
