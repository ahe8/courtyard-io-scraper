import requests
from bs4 import BeautifulSoup
import re
from enum import Enum
import json
import time
import os
from dotenv import load_dotenv


class ResultTable(Enum):
    IMAGE = 0
    TITLE = 1
    SET = 2


MINIMUM_PRICE_DIFFERENCE = 0.02  # percentage

url = "https://courtyard.io/marketplace?sortBy=listingDate%3Adesc&itemsPerPage=100&page=1&Category=Pokémon&Grader=PSA&Grade=10+GEM+MINT%3B9+MINT"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8,zh-TW;q=0.7,zh-CN;q=0.6,zh;q=0.5',
    'Accept-Encoding': 'gzip, deflate, br, zstd'
}


def process_courtyard_url(url):
    params = url.split('page=1&')[1]
    converted_url = f"https://api.courtyard.io/index/query?{params}&offset=0&limit=10&sortBy=listingDate%3Adesc"
    return converted_url


def get_courtyard_data(url):
    return requests.get(url, headers=headers)


def flatten_attributes(attributes):
    card_information = {'1st Edition': False}

    for attribute in attributes:
        attr = attribute['name']
        val = attribute['value']

        if attr == "":
            if val == '1st Edition':
               card_information['1st Edition'] = True
        elif 'Title' in attr:
            card_information['Title'] = val
        elif attr == 'Card Number':
            card_information[attr] = get_numbers_from_string(val)
        else:
            card_information[attr] = val

    return card_information


def create_name_param_for_pricecharting_search(attributes):
    with_spaces = f"{attributes['Title']} {attributes['Card Number']}"
    return with_spaces.replace(" ", "+")


def check_cache(card, cache):
    pass


def update_cache(card, cache):
    pass


def extract_prices_from_html(soup):
    elements = soup.find("div", id="full-prices").findAll('tr')
    card_information = {'prices': {}}

    for ele in elements:
        cell = ele.findChildren('td')
        grade = cell[0].text
        try:
            price = float(cell[1].text.replace("$", ""))
        except ValueError:
            price = None
        card_information['prices'][grade] = price

    card_information['last_updated'] = time.time()

    return card_information


def print_search_results(search_query, results):
    print("------------------------------")
    print("Results Found:")
    print(f"Searched: {search_query}")
    print(f"Found: {results}")
    print("------------------------------")


def get_page_from_results(search_result_soup, attributes):
    rows = search_result_soup.find("table", id="games_table").find("tbody").findAll("tr", id=re.compile(f"^product-"))

    res = []

    for row in rows:
        results = row.findAll("td")
        card_url = results[ResultTable.IMAGE.value].find('a')['href'].strip()
        title = results[ResultTable.TITLE.value].find('a').text.strip()
        card_set = results[ResultTable.SET.value].text.strip()

        if attributes['Title'].lower() not in title.lower() or \
                attributes['Card Number'] not in title or \
                (attributes['Language'] == 'Japanese' and 'Japanese' not in card_set) or \
                (attributes['Language'] == 'English' and 'Japanese' in card_set) or \
                ('Promo' in attributes['Set'] and 'Promo' not in card_set) or \
                (attributes['1st Edition'] and '1st Edition' not in title) or \
                (not attributes['1st Edition'] and '1st Edition' in title):
            continue

        if attributes['Set'].lower() in card_set.lower():
            res = [card_url]
            break

        res.append(card_url)

    if len(res) == 1 and '/game/' in res[0]:
        return requests.get(res[0])
    else:
        print_search_results(attributes, res)


def get_numbers_from_string(string):
    return re.search(r"\d+(?:\.\d+)?", string)[0]


def get_price_from_courtyard(asset):
    return asset['listing_data'][0]['price']['amount']['usd']


def get_page_from_pricecharting(params, attributes):
    search_url = f"https://www.pricecharting.com/search-products?q={params}&type=prices"
    response = requests.get(search_url, headers=headers)

    if '/game/' not in response.url:
        soup = BeautifulSoup(response.content, "html.parser")
        response = get_page_from_results(soup, attributes)

    return response


def get_prices_from_pricecharting(response):
    soup = BeautifulSoup(response.content, "html.parser")

    return extract_prices_from_html(soup)


def get_liquidity_from_pricecharting():
    pass


def get_pricecharting_price(pricecharting_prices, card_attributes):
    grader = card_attributes['Grader']
    grade = get_numbers_from_string(card_attributes['Grade'])

    grading = f"{grader} {grade}"

    if grading not in pricecharting_prices:
        grading = f'Grade {grade}'
        if grading not in pricecharting_prices:
            return

    return pricecharting_prices[grading]


def compare_prices(pricecharting_price, courtyard_price):
    return pricecharting_price >= (courtyard_price * (1 + MINIMUM_PRICE_DIFFERENCE))


def send_results_to_discord(card_name, card_img, courtyard_price, pricecharting_price, pricecharting_url, courtyard_url):
    DISCORD_WEBHOOK_URL = f"https://discord.com/api/webhooks/{os.getenv('DISCORD_WEBHOOK_ID')}/{os.getenv('DISCORD_WEBHOOK_TOKEN')}"

    price_difference = round(((1 - (pricecharting_price / courtyard_price)) * 100), 2)

    body = {
        "embeds": [
            {
                "title": card_name,
                "image": {
                    "url": card_img
                },
                "fields": [
                    {
                        "name": "courtyard.io",
                        "value": f"${courtyard_price}\n{courtyard_url}"
                    },
                    {
                        "name": "pricecharting.com",
                        "value": f"${pricecharting_price}\n{pricecharting_url}"
                    }
                ],
                "footer": {
                    "text": f"Price difference of {price_difference}%"
                }
            }
        ]
    }

    response = requests.post(DISCORD_WEBHOOK_URL, json=body)

    if response.status_code != 204:
        print(response.content)

def get_image_from_pricecharting(response):
    soup = BeautifulSoup(response.content, "html.parser")
    return soup.find("div", id="product_details").find("img")['src']

def driver():
    load_dotenv()

    # data = None
    # with open('charizard.json', 'r') as f:
    #     data = json.load(f)
    # get_courtyard_data(data)
    # assets = [data]

    courtyard_url = process_courtyard_url(url)
    response = get_courtyard_data(courtyard_url)
    data = response.json()

    assets = data['assets']
    counter = 1

    for asset in assets:
        print(counter)
        counter += 1
        attributes = flatten_attributes(asset[
                                            'attributes'])  # {'Category': 'PokÃ©mon', 'Set': 'Brilliant Stars', 'Year': '2022', 'Grader': 'PSA', 'Serial': '68350845', 'Grade': '10 GEM MINT', 'Title': 'Arceus VSTAR', 'Event': 'PokÃ©mon Starter Pack', 'Language': 'English', 'Card Type': 'Monster', 'Card Number': '176', '': ['Holo/Foil', 'Full Art']}

        # read_from_cache(attributes)
        params = create_name_param_for_pricecharting_search(attributes)

        response = get_page_from_pricecharting(params, attributes)
        if not response: continue
        pricecharting_information = get_prices_from_pricecharting(
            response)  # {'prices': {'Ungraded': 14.48, 'Grade 1': None, 'Grade 2': 5.0, 'Grade 3': 6.0, 'Grade 4': 7.0, 'Grade 5': 8.0, 'Grade 6': 9.5, 'Grade 7': 11.47, 'Grade 8': 19.0, 'Grade 9': 22.0, 'Grade 9.5': 24.0, 'SGC 10': None, 'CGC 10': 35.0, 'PSA 10': 43.0, 'BGS 10': 129.25}, 'last_updated': 1721201791.3943884}
        # update_cache(card_information)

        courtyard_price = get_price_from_courtyard(asset)  # returns float

        pricecharting_prices = pricecharting_information['prices']
        pricecharting_price = get_pricecharting_price(pricecharting_prices, attributes)

        if not pricecharting_price:
            print(
                f"Failed to get pricing information for: {asset['title']}\nhttps://courtyard.io/asset/{asset['proof_of_integrity']}")
            continue

        if compare_prices(pricecharting_price, courtyard_price):
            card_name = asset['title']
            courtyard_url = f"https://courtyard.io/asset/{asset['proof_of_integrity']}"
            pricecharting_url = response.url
            card_img = get_image_from_pricecharting(response)

            send_results_to_discord(
                card_name=card_name,
                card_img=card_img,
                pricecharting_price=pricecharting_price,
                courtyard_price=courtyard_price,
                pricecharting_url=pricecharting_url,
                courtyard_url=courtyard_url
            )


def main():
    driver()


if __name__ == "__main__":
    main()
