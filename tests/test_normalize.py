import pytest

from sponsor_check.normalize import aliases, canonical, split_trading_names


@pytest.mark.parametrize("raw, expected", [
    ("F-Secure (UK) Limited", "f secure"),
    ("CAKE GLORY LTD LTD", "cake glory"),
    ("Cake Glory Limited.", "cake glory"),
    ("The Fox Tavern", "fox tavern"),
    ('"K" Line Energy Shipping (UK) Limited', "k line energy shipping"),
    ("BW Refrigeration & Air Conditioning Limited", "bw refrigeration and air conditioning"),
    ("Café Nero Ltd", "cafe nero"),
    ("UK Ltd", "uk"),  # never normalise a name down to nothing
])
def test_canonical(raw, expected):
    assert canonical(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Everest Kitchen Ltd T/A Gurkha Swindon", ["Everest Kitchen Ltd", "Gurkha Swindon"]),
    ("HAH Hospitality Limited t/a Indian Affair Ancoats",
     ["HAH Hospitality Limited", "Indian Affair Ancoats"]),
    ("HH KITCHENS LTD Trading as Caprinos Pizza Heywood",
     ["HH KITCHENS LTD", "Caprinos Pizza Heywood"]),
    ("HAWTHORN MANOR LIMITED t/as Hawthorn Manor Residential Home",
     ["HAWTHORN MANOR LIMITED", "Hawthorn Manor Residential Home"]),
    ("16 Barrack Ltd TA Saffron Indian Restaurant", ["16 Barrack Ltd", "Saffron Indian Restaurant"]),
    ("Nirmalan Vinayagamoorthy T/A", ["Nirmalan Vinayagamoorthy"]),
    ("Tata Consultancy Services", ["Tata Consultancy Services"]),  # "ta" inside a word is not a split
])
def test_split_trading_names(raw, expected):
    assert split_trading_names(raw) == expected


def test_aliases_include_legal_and_trading():
    assert aliases("Everest Kitchen Ltd T/A Gurkha Swindon") == [
        "everest kitchen t a gurkha swindon", "everest kitchen", "gurkha swindon",
    ]
