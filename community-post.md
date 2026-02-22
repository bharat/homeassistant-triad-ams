# Cross-Integration Media Player Grouping — We Need Your Upvote!

**TL;DR:** We're proposing an *opt-in*, backwards-compatible way for `media_player` entities to support **grouping across different integrations** (e.g., Sonos speakers + audio matrix/AVR zones).

👉 Please upvote the architecture discussion: **<https://github.com/home-assistant/architecture/discussions/1331>**

Hey everyone,

We've been working on a small but meaningful improvement to `media_player` that we think a lot of people will benefit from: **cross-integration grouping**.

## The Problem

Today, `media_player` “grouping” in Home Assistant is **integration-defined**. While many integrations support grouping within their own ecosystem (e.g., Sonos), there’s **no standard, opt-in API** for an integration to expose a curated set of *groupable* `media_player` entities **from other integrations**.

That means the UI can’t reliably offer cross-integration grouping controls, even when the underlying audio path is real. For example, if a Sonos speaker feeds into a Triad AMS audio matrix (or any similar hardware routing setup), you can’t present them as a single controllable “group” in Home Assistant - even though the audio is physically flowing from one to the other.

### Quick example

- **Before:** Sonos speaker (Sonos integration) + Triad output zone (Triad integration) can’t be grouped in the UI.
- **After:** The Triad integration can expose a curated set of “groupable players” (including Sonos entities), enabling a single group control in the UI.

## What We've Built

We've implemented an optional `get_groupable_players` extension to the `media_player` entity model. It lets an integration return a curated list of players it can group with — **including players from other integrations**.

**Scope / expectations:**

- This is **opt-in** per integration and **fully backward compatible**.
- It does **not** force unrelated players to sync if the underlying platform can’t do it—integrations only expose pairings that make sense.

We have working PRs for core, frontend, and documentation:

- **Core:** [home-assistant/core#161656](https://github.com/home-assistant/core/pull/161656)
- **Frontend:** [home-assistant/frontend#29200](https://github.com/home-assistant/frontend/pull/29200)
- **Docs:** [home-assistant/home-assistant.io#43269](https://github.com/home-assistant/home-assistant.io/pull/43269)
- **Developer docs:** [home-assistant/developers.home-assistant#2934](https://github.com/home-assistant/developers.home-assistant/pull/2934)

And a reference implementation in the Triad AMS integration (**upstream PR**):
<https://github.com/bharat/homeassistant-triad-ams/pull/63>
It demonstrates cross-platform grouping between Sonos speakers and Triad output zones — working today.

## Who This Helps

- Audio matrices (Triad, HTD, etc.)
- AVR / multi-zone setups where “zones” and “sources” don’t come from the same integration
- Any installation where the *control surface* in HA spans multiple audio ecosystems

## How You Can Help

Since this changes the entity model, it requires approval through an [architecture discussion](https://github.com/home-assistant/architecture/discussions/1331). The more community support (and real-world use cases) it gets, the more likely it is to move forward.

**Please upvote by clicking the up-arrow:**
👉 [**home-assistant/architecture#1331**](https://github.com/home-assistant/architecture/discussions/1331)

Even better: leave a short comment with your setup (integrations involved + what you’re trying to group).

The original feature request with full technical details is here: [Discussion #2342](https://github.com/orgs/home-assistant/discussions/2342)

Thanks for reading — and thanks for your support!
