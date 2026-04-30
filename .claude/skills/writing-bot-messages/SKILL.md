---
name: writing-bot-messages
description: Use when writing or modifying Telegram bot messages in workflow steps - ensures messages explain context, fit the user's journey, and include proper UI elements (buttons, banners)
---

# Writing Bot Messages

## Overview

Every message in a bot is part of a user journey. A message without context confuses the user; a message with context guides them. This skill ensures each message:
- **Explains the user's position** in the workflow ("you are here")
- **Explains what's happening next** (without spoilers)
- **Fits the overall narrative** of why the bot exists
- **Always includes UI** (buttons, banners) — no message stands alone

## When to Use

Write messages when:
- Creating or modifying any step in a workflow
- Adding new screens or refactoring flow
- Reviewing messages that feel disconnected or unclear

## The Problem

Without this skill, Claude writes messages that:
- ❌ Don't explain the user's position ("choose a photo" — which photo? why?)
- ❌ Don't connect to the bigger story (why are we doing this?)
- ❌ Assume the user knows what comes next
- ❌ Get written without considering what buttons/banners they need

## The Solution: Message Structure

Every message has **3 layers**:

### Layer 1: User Position (where are they?)
**The first sentence tells the user where they are in the journey.**

```
❌ BAD: "Enter the article"
✅ GOOD: "Step 2: Finding your product — Enter a Wildberries article number"
```

Why? The user just clicked something. They might not remember why. Tell them immediately.

### Layer 2: Context (why is this step happening?)
**One sentence explaining why they're here — what problem does this solve?**

```
❌ BAD: "Select the best photo"
✅ GOOD: "Step 3: Select the photos you like best — we'll create a beautiful reference from them"
```

Connect the step to the bigger story. Why do we need to select photos? Because we need a good reference. Why? Because everything else depends on it.

### Layer 3: Action (what should they do?)
**Clear instruction on what button to press next.**

```
✅ GOOD: "Tap 'Next →' to continue"
```

### The First Message Is Special

The very first message in a flow must explain **why the bot exists**.

```
Step 1a: Welcome

The problem: You sell on Wildberries or Ozon but ads work like a taxi meter — 
you pay to drive, stop paying and you stop moving.

The solution: Pinterest traffic that keeps working after you pay once.

This bot creates Pinterest pins for your products automatically.

→ Tap 'Next' to see how it works
```

This tells the user:
- **Problem** (I understand your pain)
- **Solution** (I have an answer)
- **What this bot does** (here's the tool)
- **What to do next** (tap Next)

## UI Requirements (Critical)

**Every message must have:**

1. **Buttons** — Don't leave the user hanging
   - `kb_back()` and `kb_next()` for navigation
   - `kb_start()` for entry points
   - Never a message without a keyboard

2. **Banner** — A width anchor for readability
   - Default: `assets/banner_default.png`
   - Or step-specific banner from DB: `await get_banner("msg_name")`

3. **Message text in DB** — Not hardcoded
   - Store in `prompt_templates` table
   - Fetch with: `await get_template("msg_name")`

4. **Flow state in code** — Not in the message
   - Use `edit_message_text()` to update the same message
   - Don't create new messages to "clear" the screen

## Real Example: Onboarding Flow (00)

Workflow: Steps 1a-1d (one screen that refreshes)

**Step 1a:**
```
Text: "Step 1a: Welcome\n\nThe problem: ads work like a taxi meter...\n\nTap 'Next →'"
Buttons: [Next →]
Banner: assets/banner_default.png
Edit: edit_message_media() to replace with 1b
```

**Step 1b:**
```
Text: "Step 1b: Understanding Pinterest\n\nYou already know this loop:\n💸 Raise bid — sales go up\n...\n\nTap 'Next →'"
Buttons: [← Back] [Next →]
Edit: edit_message_media() to replace with 1c or back to 1a
```

**Step 1d (last):**
```
Text: "Step 1d: Results from real sellers\n\n📍 Niches: clothing, home...\n📈 Average: 500-3000 organic visits/month\n\nReady to try? Tap 'Start'"
Buttons: [← Back] [Start →]
Edit: After click → move to Step 2 (profile/menu)
```

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Message doesn't say which step it is | Add "Step Xa: [Name]" as first line |
| User doesn't know why they're here | Add one sentence explaining the problem/need |
| Message is too long (>3 paragraphs) | Cut 50%. Users read fast. |
| No buttons attached | Every message gets buttons + banner |
| Hardcoded text instead of DB | Store in `prompt_templates`, fetch with `get_template()` |
| Multiple messages created per step | Use `edit_message_media()` for refreshes, not new messages |
| Message disconnected from overall narrative | Link it to "why does the bot exist?" |

## Workflow Checklist

Before writing a message, ask:

- [ ] **Position clear?** Does the user know which step they're on?
- [ ] **Context explained?** Why is this step happening?
- [ ] **Connected to story?** How does this fit the bigger picture?
- [ ] **Action clear?** What button should they press?
- [ ] **UI complete?** Buttons + banner + DB template included?
- [ ] **Flow state managed?** Using `edit_message_media()` not new messages?
- [ ] **Keyboard chosen?** Right buttons for this step (`kb_back()`, `kb_next()`, etc.)?

If any answer is "no" — rewrite before committing.

## Key Principle

**Messages are not standalone text.**

Each message is one frame in a movie. The user is watching the story unfold. Your job is to:
- Tell them where they are
- Explain why they're there
- Show them what comes next
- Guide them with buttons

The story is larger than any single message. Write with the whole journey in mind.
