# Example: Black Friday email for lapsed VIPs

Illustrative only. The project, segment, engine, pool, sender and URLs are made up.

**Prompt:** "Build a Black Friday email for our lapsed VIPs: three product picks and a 20% code."

## Questions asked (one message)

> A few things before I build it:
> 1. The code: is there a voucher pool for it, or a single code to print? I found a pool "Black Friday 20" with codes available.
> 2. Where should the main button go?
> 3. Which recommendation engine for the three picks? The project has "Personal picks" and "Bestsellers".
> 4. Audience: segmentation "Customer value tiers" has a segment "Lapsed VIP". Use that?
>
> Note: Loomi Connect creates email campaigns as raw HTML, so this opens in the HTML editor, not the drag-and-drop builder.

The user answered: the pool, `https://www.acme-outdoor.example/black-friday`, "Personal picks", and yes.

## Subject and preheader options

| # | Subject | Why |
|---|---|---|
| 1 | Your VIP 20% is waiting, {{ customer['first_name'] \| default('there', true) }} | Personal, states the benefit |
| 2 | Black Friday starts early for VIPs | Exclusivity |
| 3 | We saved you three picks (and 20% off) | Curiosity plus benefit |

| # | Preheader |
|---|---|
| 1 | Three picks we think you'll love, plus a code that ends Sunday. |
| 2 | First access before everyone else. Ends Sunday. |
| 3 | Your code is inside. |

The user chose subject 1 and preheader 1.

## Plan (before the write)

```
Project: Demo Retail
Will create ONE email campaign draft (nothing is scheduled or sent):
  Name:      Black Friday - lapsed VIPs - DRAFT
  Subject:   Your VIP 20% is waiting, {{ customer['first_name'] | default('there', true) }}
  Preheader: Three picks we think you'll love, plus a code that ends Sunday.
  Sender:    Acme Outdoor <sender address, shown in full> (the project default)
  Audience:  segment 'Lapsed VIP' of segmentation 'Customer value tiers'   Consent: newsletter
  Image hosts: (from data), brxcdn.com
  Link hosts:  www.acme-outdoor.example
  Body:      raw HTML, 3 KB, 2 images, 5 links; unsubscribe and postal address in the footer
  Warnings:  product images come from the catalog, so their host is checked at render time;
             no send time is set: set it in Engagement before starting
Create this draft? (yes / no)
```

(The full HTML was shown in a code block above the question.)

An earlier `plan` run was **blocked** with two problems, both fixed before this confirmation:

| Check | Problem | Fix |
|---|---|---|
| unknown_host | Image is loaded from cdn.partner-ads.example | Logo swapped for the media library copy |
| placeholder | `%%POSTAL_ADDRESS%%` left in | `{{ project_variables.company_address }}` |

## Result (after "yes")

```
## Email draft: Black Friday - lapsed VIPs - DRAFT (Demo Retail)

**Created:** draft 65f0c0ffee0000000000abcd (verified: in_place). Nothing is scheduled or sent.
**Subject / preheader:** Your VIP 20% is waiting, {{ customer['first_name'] | default('there', true) }} / Three picks we think you'll love, plus a code that ends Sunday.
**Audience:** segment 'Lapsed VIP' · **Consent:** newsletter · **Sender:** project default
**Content:** "We've missed you"; offer from voucher pool 'Black Friday 20'; 3 recommended products from 'Personal picks'
**Warnings:** product image hosts checked at render time; no send time set

**Next:** run campaign-qa on this draft, then set the send time and start it in the Engagement UI.
```
