# Example: boots weekend text for lapsed VIPs

Illustrative only. The project, segment, sender and URLs are made up.

**Prompt:** "Write a text for our lapsed VIPs: 20% off boots this weekend, link to go.acme-outdoor.example/boots."

## Questions asked (one message)

> A few things before I write it:
> 1. Where can recipients be: the US only, or Canada too? Any states left out?
> 2. Should it go at a set time? If not, it's saved to send as soon as someone starts it in Engagement.
> 3. Audience: segmentation "Customer value tiers" has a segment "Lapsed VIP". Use that?
> 4. Consent: the project has an "SMS marketing" category. Use that?

The user answered: US only, Saturday 11 a.m. Eastern, yes, yes.

## Message options

| # | Message | Encoding | Segments |
|---|---|---|---|
| 1 | Acme Outdoor: Hi {{ customer['first_name'] \| default('there', true) }}, 20% off boots ends Sunday. https://go.acme-outdoor.example/boots Reply STOP to opt out, HELP for help | GSM-7, 132 chars | 1 |
| 2 | Acme Outdoor: VIP weekend - 20% off all boots until Sunday. https://go.acme-outdoor.example/boots Reply STOP to opt out, HELP for help | GSM-7, 134 chars | 1 |
| 3 | Acme Outdoor: we saved you 20% on boots this weekend only. https://go.acme-outdoor.example/boots Reply STOP to opt out, HELP for help | GSM-7, 133 chars | 1 |

The user chose option 1.

An earlier draft of option 2 used "VIP weekend – 20% off" with an en dash. The plan warned that the dash forces UCS-2 (`ucs2_single_chars` per SMS, so 2 segments); it was swapped for a hyphen.

## Plan (before the write)

```
Project: Demo Retail
Will create ONE SMS campaign draft (nothing is started or sent):
  Name:     Boots weekend - lapsed VIPs - SMS DRAFT
  Message:  Acme Outdoor: Hi {{ customer['first_name'] | default('there', true) }}, 20% off boots ends Sunday. https://go.acme-outdoor.example/boots Reply STOP to opt out, HELP for help
            GSM-7, 132 characters (each {{ }} counted as 12), 1 segment
  Translations: none
  Sender:   Acme Outdoor (AcmeOutdr) (the project default)
  Audience: segment 'Lapsed VIP' of segmentation 'Customer value tiers'   Consent: SMS marketing
  Link hosts: go.acme-outdoor.example
  Regions:  US (as you said)
  Schedule: at 2026-11-14 08:00 (saturday, UTC-08:00), 09:00 (UTC-07:00), 10:00 (UTC-06:00), 11:00 (UTC-05:00)
            once someone starts it in the Engagement UI; checked against quiet hours for the US
  Warnings: 8 a.m. Pacific is outside the 9 a.m. start in Texas, Minnesota and Rhode Island (only if recipients
            can be there); Florida, Oklahoma and Maryland allow 3 texts per 24 hours; Texas SB 140 registration;
            silent hours must be set in the Engagement UI
Create this draft? (yes / no)
```

The user moved the send to 12 p.m. Eastern, which cleared the state-window warnings, and said yes.

## Result (after "yes")

```
## SMS draft: Boots weekend - lapsed VIPs - SMS DRAFT (Demo Retail)

**Created:** draft 65f0c0ffee0000000000beef (verified: in_place). Nothing is started or sent.
**Message:** Acme Outdoor: Hi {{ customer['first_name'] | default('there', true) }}, 20% off boots ends Sunday. https://go.acme-outdoor.example/boots Reply STOP to opt out, HELP for help (GSM-7, 1 segment)
**Audience:** segment 'Lapsed VIP' · **Consent:** SMS marketing · **Sender:** Acme Outdoor (project default)
**Schedule:** Saturday 12:00 Eastern (09:00 Pacific) once started
**Warnings:** 3-per-24-hours states; Texas SB 140; silent hours not set

**Next:** set silent hours (recipient time zone) in the Engagement UI, then run campaign-qa on this draft before starting it.
```
