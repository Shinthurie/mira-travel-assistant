"""Reply wording built by code. Anything containing a number comes from engine output only.

Brand tone of voice: short sentences, plain English, warm but not gushing, no exclamation marks
in prices or policies, "we" for the company and "I" for Mira.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from mira.pricing.schemas import NoQuote, NoQuoteReason, QuoteForTraveller

INTRO = ("Hello, I'm Mira from Ceylon Compass Holidays. I can suggest tours, answer questions from our tour "
         "pages, and give you a confirmed price. What kind of trip are you thinking of: a day tour, a few days, "
         "or a longer custom trip?")

GREETING_AGAIN = ("Hello again. Tell me where you'd like to go, your dates or who's travelling, "
                  "and I'll find the right tour and a confirmed price.")

OFF_TOPIC = ("I can only help with travel in Sri Lanka with Ceylon Compass Holidays, so I'll leave that one. "
             "Shall we look at a trip? Tell me where you'd like to go or what you'd like to see.")

INJECTION = ("I can't change how I work or how we price, and I can't offer discounts. "
             "What I can do is give you our normal confirmed price.")

DISCOUNT = ("I'm not able to offer discounts. Our prices come straight from our rates, "
            "so every traveller pays the same fair price.")

PER_PERSON = ("We quote one total price per booking, not per person, so I can't split it. "
              "The total for your group is the price shown.")

CURRENCY = ("We quote in US dollars only, so I can't convert the price. Your bank or card provider will "
            "show you the amount in your own currency when you pay.")

TEASER = ("The \"from\" prices on older pages are not quotes. I'll only show you a price worked out from "
          "our current rates for your exact dates and group.")

FORGOT = "Done. I've deleted what I remembered about you. Future chats start fresh."

PLACES_QUESTION = ("Here are a few tours that could suit. Is there a place you'd love to see, or something you'd "
                   "like to do, such as beaches, wildlife, tea country or temples? I'll narrow it down.")

QUESTIONS = {
    "tour": "Which trip would you like: a day tour, a few days away, or a longer round trip? If you have a place "
            "in mind, tell me and I'll find the closest tours.",
    "travellers": "Who's travelling? Tell me how many adults, and the ages of any children.",
    "start_date": "What date would you like to start?",
}

NO_QUOTE_REASON_TEXT = {
    NoQuoteReason.NO_RATES_FOR_TOUR: "We don't have published rates for this tour yet.",
    NoQuoteReason.MISSING_RATE: "One of the hotels on this tour has no rate for your group.",
    NoQuoteReason.EXPIRED_RATE: "Our hotel rates for this tour have expired and are being renewed.",
    NoQuoteReason.CONFLICTING_RATE: "Our hotel rates for your dates need to be checked.",
    NoQuoteReason.BEYOND_RATE_VALIDITY: "Our current rates only run until 31 October 2027.",
    NoQuoteReason.GROUP_TOO_LARGE: "Private tours are for up to 20 travellers, so our team plans larger groups.",
    NoQuoteReason.TOUR_NOT_QUOTABLE: "This page is a past offer and can't be booked now.",
    NoQuoteReason.TOUR_NOT_PUBLISHED: "That tour isn't available.",
    NoQuoteReason.UNKNOWN_TOUR: "I couldn't find that tour in our catalogue.",
    NoQuoteReason.START_DATE_IN_PAST: "That date has already passed.",
    NoQuoteReason.INVALID_TRAVELLERS: "I need at least one adult on the booking.",
    NoQuoteReason.RATE_DATA_UNUSABLE: "Our rates for this tour need checking.",
}


def usd(amount: Decimal | str) -> str:
    """'USD 2,965' (whole dollars; engine prices are always whole)."""
    value = Decimal(str(amount))
    return f"USD {value:,.0f}" if value == value.to_integral_value() else f"USD {value:,.2f}"


def nice_date(d: date) -> str:
    return f"{d.day} {d.strftime('%B %Y')}"


def quote_text(q: QuoteForTraveller) -> str:
    """The price sentence. Every number comes from QuoteForTraveller."""
    lines = [f"Here's your confirmed price for {q.tour_title}, starting {nice_date(q.start_date)}, "
             f"for {q.travellers_summary}: {usd(q.price_usd)} in total."]
    if q.pay_in_full:
        lines.append(f"This is paid in full when you book ({usd(q.deposit_usd)}).")
    else:
        lines.append(f"A deposit of {usd(q.deposit_usd)} confirms it. The balance of {usd(q.balance_usd)} "
                     f"is due by {nice_date(q.balance_due_date)}.")
    return " ".join(lines)


def no_quote_text(nq: NoQuote) -> str:
    reason = NO_QUOTE_REASON_TEXT.get(nq.reason, "")
    if nq.reason in (NoQuoteReason.START_DATE_IN_PAST, NoQuoteReason.INVALID_TRAVELLERS,
                     NoQuoteReason.TOUR_NOT_PUBLISHED, NoQuoteReason.UNKNOWN_TOUR):
        return f"{reason} Could you check the details?" if nq.reason in (
            NoQuoteReason.START_DATE_IN_PAST, NoQuoteReason.INVALID_TRAVELLERS) else \
            f"{reason} I can pass your request to our team, and a specialist will get back to you."
    return f"{reason} I can't give you a confirmed price, so a specialist from our team will check it and " \
           f"get back to you. I've passed it on."
