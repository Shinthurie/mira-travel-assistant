"""Regressions for the problems seen in the live demo (27 Nov). Offline (rules) mode, plus fake-model replays."""

from mira.agent.nodes import LLMExtraction
from mira.agent.state import Intent
from mira.llm import FakeLLM
from tests.agent_helpers import chat, components, fresh_agent


def _tours(turn: dict) -> list[str]:
    shelf = [c for c in turn["components"] if c["component"] == "TourShelf"]
    return [t["title"] for t in shelf[0]["props"]["tours"]] if shelf else []


def test_misspelled_places_are_recognised_but_ordinary_words_are_not():
    ctx, _ = fresh_agent()
    r = ctx.resolver
    assert r.places_in("i want a pacakge to elle and kandy") == {"ella", "kandy"}
    assert r.places_in("trip to colmbo and sigirya") == {"colombo", "sigiriya"}
    assert r.places_in("Nuwara Elya for 2") == {"nuwara-eliya"}
    assert r.places_in("tell me about the tour") == set()
    assert r.places_in("I want to visit the gallery") == set()  # not Galle


def test_package_to_misspelled_places_shows_the_tours_that_visit_them():
    """Demo issue 1: 'i want a pacakge to elle and kandy' got 'I don't have a tour that covers Ella'."""
    _, graph = fresh_agent()
    turn = chat(graph, ["i want a pacakge to elle and kandy"])[0]
    assert "These tours visit Ella and Kandy" in turn["final_text"]
    assert {"Instafamous Sri Lanka", "Treasures of Sri Lanka"} <= set(_tours(turn))
    assert "don't have a tour" not in turn["final_text"]


def test_go_to_a_place_shows_tours_not_a_paragraph():
    """Demo issues 2 and 4: 'i want go to galle' / 'i want to go to kandy' got paragraphs and no tours."""
    _, graph = fresh_agent()
    turn = chat(graph, ["i want go to galle"])[0]
    assert "These tours visit Galle" in turn["final_text"] and "Galle Fort Walking Tour" in _tours(turn)
    _, graph = fresh_agent()
    turn = chat(graph, ["i want to  go to kandy"])[0]
    assert "These tours visit Kandy" in turn["final_text"] and "Kandy City Tour" in _tours(turn)


def test_tell_me_about_a_place_describes_it_and_shows_its_tours():
    _, graph = fresh_agent()
    turn = chat(graph, ["Tell me about Kandy"])[0]
    assert turn["final_text"].startswith("Kandy was the last royal capital")
    assert "Children" not in turn["final_text"]  # it used to open with the children policy
    assert "Kandy City Tour" in _tours(turn)


def test_a_place_without_a_page_still_answers_from_the_tour_pages():
    """Seed S17 stays as the brief expects."""
    _, graph = fresh_agent()
    turn = chat(graph, ["Tell me about Polonnaruwa."])[0]
    assert "Polonnaruwa" in turn["final_text"] and turn["citations"]


def test_follow_up_about_the_one_tour_just_discussed_uses_that_tour():
    """Demo issue 3: 'can you give more details and price' got 'I can't give a price' and another tour."""
    _, graph = fresh_agent()
    turns = chat(graph, ["Tell me about the Galle Fort walking tour", "can you give more details and price"])
    assert "TravellerPicker" in components(turns[1])
    assert "can't give a price" not in turns[1]["final_text"]


def test_follow_up_after_several_tours_asks_which_one_even_if_the_model_calls_it_a_question():
    llm = FakeLLM([LLMExtraction(intent=Intent.QUOTE, wants_price=True),
                   LLMExtraction(intent=Intent.INFO, wants_info=True, wants_price=True)])
    _, graph = fresh_agent(llm=llm)
    turns = chat(graph, ["i want go to galle", "can you give more details and price"])
    assert turns[1]["final_text"].startswith("Which tour would you like")
    assert "SpecialistHandoff" not in components(turns[1]) and "TourCard" not in components(turns[1])


def test_switching_destination_never_reprices_the_previous_tour():
    """Demo issue 5: after a Treasures quote, 'okay i want to galle instead' re-priced Treasures (USD 4,550)."""
    _, graph = fresh_agent()
    turns = chat(graph, ["i want to go to kandy", "I'd like a price for Treasures of Sri Lanka.",
                         "We are 2 adults and no children, starting 25 November 2026.",
                         "okay i want to galle instead", "I'd like a price for Galle Fort Walking Tour."])
    assert turns[2]["pricing"]["tour_id"] == "T12"
    assert turns[3].get("pricing") is None and "PriceBreakdown" not in components(turns[3])
    assert "These tours visit Galle" in turns[3]["final_text"]
    assert turns[4]["pricing"]["tour_id"] == "T04"  # the tour they picked, same travellers and date


def test_a_message_without_a_place_keeps_the_chosen_tour():
    _, graph = fresh_agent()
    turns = chat(graph, ["Whale watching in Mirissa on 15 March 2027 for 2 adults. Price?", "I want to book it"])
    assert "BookingForm" in components(turns[1])


def test_booking_never_uses_a_quote_for_a_different_tour():
    """Changing details: 'Yes the Cultural Triangle one' after a Kandy City Tour quote opened a Kandy City Tour form."""
    llm = FakeLLM([LLMExtraction(intent=Intent.QUOTE, wants_price=True, tour_id="T02", adults=2, start_date="2027-02-05"),
                   LLMExtraction(intent=Intent.BOOK, tour_id="T09")])
    _, graph = fresh_agent(llm=llm)
    turns = chat(graph, ["How much is the Kandy City Tour for 2 adults on 5 February 2027?", "Yes the Cultural Triangle one"])
    assert turns[0]["pricing"]["tour_id"] == "T02"
    assert "Kandy City Tour" not in turns[1]["final_text"] and "BookingForm" not in components(turns[1])
    assert turns[1]["pricing"]["tour_id"] == "T09"  # the tour they named is priced first (here: a no-price window)


def test_details_given_in_pieces_are_acknowledged_and_which_tour_is_asked():
    _, graph = fresh_agent()
    turns = chat(graph, ["We want a few days in the hill country", "2 adults", "15 June 2027"])
    assert turns[1]["final_text"].startswith("Got it: 2 adults.")
    assert "Which tour would you like a price for" in turns[1]["final_text"]
    assert "Got it: 2 adults, starting 15 June 2027." in turns[2]["final_text"]
    assert "Which tour would you like" not in turns[2]["final_text"]  # never the same question twice
    assert "tap Get a price on its card" in turns[2]["final_text"]
    assert "TourCard" not in components(turns[2])  # the tours are just above; no repeat


def test_a_month_alone_never_becomes_an_invented_date():
    llm = FakeLLM([LLMExtraction(intent=Intent.QUOTE, tour_id="T09", adults=2, start_date="2027-06-01")])
    ctx, graph = fresh_agent(llm=llm)
    turn = chat(graph, ["Cultural Triangle for 2 adults in June"])[0]
    assert turn.get("pricing") is None  # no price for a day the traveller never chose
    assert "TravellerPicker" in components(turn)


def test_children_12_and_over_are_explained_when_priced_as_adults():
    _, graph = fresh_agent()
    turn = chat(graph, ["Whale watching in Mirissa on 15 March 2027 for 2 adults and kids aged 7 and 12, how much?"])[0]
    assert turn["pricing"]["kind"] == "quote"
    assert "Children aged 12 and over are priced as adults" in turn["final_text"]


def test_no_price_message_names_the_tour_and_date():
    _, graph = fresh_agent()
    turn = chat(graph, ["Kandy Heritage Stay for 2 adults from 20 January 2027"])[0]
    assert turn["final_text"].startswith("For Kandy Heritage Stay starting 20 January 2027:")
