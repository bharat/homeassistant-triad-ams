# Cross-Integration Media Player Grouping — We Need Your Upvote!

Hey everyone,

We've been working on a small but meaningful improvement to `media_player` that we think a lot of people will benefit from: **cross-integration grouping**.

## The Problem

Today, Home Assistant only lets you group media players from the **same integration**. If you have a Sonos speaker feeding into a Triad AMS audio matrix (or any similar hardware routing setup), you can't group them together in the UI — even though the audio is physically flowing from one to the other.

This limitation affects anyone with multi-room audio that spans different platforms — matrix audio switches, AVR inputs, or any setup where sources and speakers come from different integrations.

## What We've Built

We've implemented an optional `get_groupable_players` extension to the `media_player` entity model. It lets an integration return a curated list of players it can group with — **including players from other integrations**. It's fully backward compatible: integrations that don't implement it are completely unaffected.

We have working PRs for core, frontend, and documentation:

- **Core:** [home-assistant/core#161656](https://github.com/home-assistant/core/pull/161656)
- **Frontend:** [home-assistant/frontend#29200](https://github.com/home-assistant/frontend/pull/29200)
- **Docs:** [home-assistant/home-assistant.io#43269](https://github.com/home-assistant/home-assistant.io/pull/43269)
- **Developer docs:** [home-assistant/developers.home-assistant#2934](https://github.com/home-assistant/developers.home-assistant/pull/2934)

And a reference implementation in the [Triad AMS integration](https://github.com/bharat/homeassistant-triad-ams/pull/63) that demonstrates cross-platform grouping between Sonos speakers and Triad output zones — working today.

## How You Can Help

Since this changes the entity model, it requires approval through an [architecture discussion](https://github.com/home-assistant/architecture/discussions/1331). The more community support it gets, the more likely it is to move forward.

**If you'd like to see cross-integration media player grouping in Home Assistant, please upvote the architecture discussion by clicking the up-arrow:**

👉 [**home-assistant/architecture#1331**](https://github.com/home-assistant/architecture/discussions/1331)

The original feature request with full technical details is here: [Discussion #2342](https://github.com/orgs/home-assistant/discussions/2342)

Thanks for reading — and thanks for your support!
