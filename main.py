import sys
import requests
from bs4 import BeautifulSoup
import re
from enum import Enum
import os
from dotenv import load_dotenv
import time


class ResultTable(Enum):
    IMAGE = 0
    TITLE = 1
    SET = 2


MINIMUM_PRICE_DIFFERENCE = 0.15  # percentage
NUMBER_OF_CARDS_TO_CHECK = 50

default_url = "https://courtyard.io/marketplace?sortBy=listingDate%3Adesc&itemsPerPage=100&page=1&Category=Pokémon&Grader=PSA&Grade=10+GEM+MINT%3B9+MINT"

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8,zh-TW;q=0.7,zh-CN;q=0.6,zh;q=0.5',
}


def process_courtyard_url(url, offset=0):
    params = url.split('page=1&')[1]
    converted_url = f"https://api.courtyard.io/index/query?{params}&offset={offset}&limit=100&sortBy=listingDate%3Adesc"
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
        # elif 'Title' in attr:
        #     card_information['Title'] = val
        # elif attr == 'Card Number':
        #
        #     card_information[attr] = get_numbers_from_string(val)
        else:
            card_information[attr] = val

    return card_information


def create_name_param_for_pricecharting_search(attributes):
    if 'Card Number' in attributes:
        with_spaces = f"{attributes['Title']} {attributes['Card Number']}"
    else:
        with_spaces = attributes['Title']
    return with_spaces.replace(" ", "+")


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

    return card_information


def print_search_results(search_query, results):
    print("------------------------------")
    print("Results Found:")
    print(f"Searched: {search_query}")
    print(f"Found: {results}")
    print("------------------------------")


def get_page_from_results(search_result_soup, attributes):
    result = search_result_soup.find("table", id="games_table")
    if not result:
        return
    rows = result.find("tbody").findAll("tr", id=re.compile(f"^product-"))

    res = []

    for row in rows:
        results = row.findAll("td")
        card_url = results[ResultTable.IMAGE.value].find('a')['href'].strip()
        title = results[ResultTable.TITLE.value].find('a').text.strip()
        card_set = results[ResultTable.SET.value].text.strip()

        if attributes['Title'].lower() not in title.lower() or \
                ('Card Number' in attributes and attributes['Card Number'] not in title) or \
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
    # else:
    #     print_search_results(attributes, res)


def get_numbers_from_string(string):
    match = re.search(r"\d+(?:\.\d+)?", string)
    if not match.group(0):
        print(match)
        print(string)
        return
    return match.group(0)



def get_price_from_courtyard(asset):
    return asset['listing_data'][0]['price']['amount']['usd']


def get_page_from_pricecharting(params, attributes):
    search_url = f"https://www.pricecharting.com/search-products?q={params}&type=prices"
    response = requests.get(search_url, headers=headers)

    if '/game/' not in response.url:
        soup = BeautifulSoup(response.content, "html.parser")
        response = get_page_from_results(soup, attributes)

    return response


def get_prices_from_pricecharting(soup):
    return extract_prices_from_html(soup)


def get_liquidity_from_pricecharting(soup):
    liquidity_info = soup.find('tr', class_='sales_volume').find_all('a')
    return list(map(lambda x: x.text, liquidity_info))


def get_volume_from_pricecharting(liquidity_information, card_attributes):
    grade = get_numbers_from_string(card_attributes['Grade'])
    lookup_table = {
        '': 0,
        '7': 1,
        '8': 2,
        '9': 3,
        '9.5': 4,
        '10': 5,
    }
    if grade in lookup_table:
        return liquidity_information[lookup_table[grade]]


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


def get_discord_webhook_url(webhook_type=None):
    if not webhook_type:
        webhook_id = "DISCORD_WEBHOOK_COURTYARD_ID"
        webhook_token = "DISCORD_WEBHOOK_COURTYARD_TOKEN"
    else:
        webhook_id = "DISCORD_WEBHOOK_OFFERS_ID"
        webhook_token = "DISCORD_WEBHOOK_OFFERS_TOKEN"

    try:
        return f"https://discord.com/api/webhooks/{os.environ[webhook_id]}/{os.environ[webhook_token]}"
    except KeyError:
        return f"https://discord.com/api/webhooks/{os.getenv(webhook_id)}/{os.getenv(webhook_token)}"


def send_results_to_discord(card_name, card_img, courtyard_price, pricecharting_price, pricecharting_url,
                            courtyard_url, volume):
    DISCORD_WEBHOOK_URL = get_discord_webhook_url()

    price_difference = round(((1 - (pricecharting_price / courtyard_price)) * 100), 2)

    body = {
        "embeds": [
            {
                "title": card_name,
                'description': f"Volume: {volume}",
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


def send_courtyard_offer_to_discord(offer_price, listing_price, asset):
    DISCORD_WEBHOOK_URL = get_discord_webhook_url("offers")

    price_difference = round(((1 - (offer_price / listing_price)) * 100), 2)

    card_name = asset['title']
    card_img = asset['image']
    courtyard_url = f"https://courtyard.io/asset/{asset['proof_of_integrity']}"

    body = {
        "embeds": [
            {
                "title": card_name,
                'url': courtyard_url,
                "image": {
                    "url": card_img
                },
                "fields": [
                    {
                        "name": "Listing Price",
                        "value": f"${listing_price}"
                    },
                    {
                        "name": "Top Offer",
                        "value": f"${offer_price}"
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


def log_to_discord():
    pass


def check_courtyard_offers(listing_price, asset):
    best_price = 0
    SELLING_FEE = 0.065

    if 'offer_data' in asset:
        offers = asset['offer_data']

        for offer in offers:
            best_price = max(best_price, offer['price']['netAmount']['usd'])

        if best_price >= (listing_price * (1 + SELLING_FEE)):
            send_courtyard_offer_to_discord(best_price, listing_price, asset)


def get_image_from_pricecharting(soup):
    return soup.find("div", id="product_details").find("img")['src']


def update_github_repo_variable(last_result):
    auth_token = os.environ['GH_REPO_VARIABLES_AUTH_TOKEN']
    github_headers = {
        "Authorization": f"Bearer {auth_token}",
        "X-GitHub-Api-Version": "2022-11-28"
    }
    api_url = "https://api.github.com/repos/ahe8/cys/actions/variables/LAST_SERIAL_FETCHED"

    body = {"name": "LAST_SERIAL_FETCHED", "value": str(last_result)}

    response = requests.patch(api_url, json=body, headers=github_headers)

    if response.status_code == 204:
        print(f"Updated Last Serial Fetched: {last_result}")
    else:
        print(response.content)


def driver(url=default_url):
    load_dotenv()

    last_processed_serial = os.environ.get('LAST_SERIAL_FETCHED')

    print(f"Last Serial Fetched: {last_processed_serial}")

    courtyard_url = process_courtyard_url(url)
    response = get_courtyard_data(courtyard_url)
    data = response.json()

    assets = data['assets']

    for i in range(NUMBER_OF_CARDS_TO_CHECK):
        asset = assets[i]

        attributes = flatten_attributes(asset['attributes'])
        if last_processed_serial == str(attributes['Serial']):
            break

        if attributes['Language'] != "English" and attributes['Language'] != "Japanese":
            continue

        params = create_name_param_for_pricecharting_search(attributes)
        response = get_page_from_pricecharting(params, attributes)
        if not response: continue
        time.sleep(1)

        soup = BeautifulSoup(response.content, "html.parser")

        pricecharting_information = get_prices_from_pricecharting(soup)
        pricecharting_prices = pricecharting_information['prices']
        pricecharting_url = response.url

        card_img = get_image_from_pricecharting(soup)

        liquidity_info = get_liquidity_from_pricecharting(soup)

        card_name = asset['title']

        courtyard_url = f"https://courtyard.io/asset/{asset['proof_of_integrity']}"
        courtyard_price = get_price_from_courtyard(asset)

        pricecharting_price = get_pricecharting_price(pricecharting_prices, attributes)

        check_courtyard_offers(courtyard_price, asset)

        volume = get_volume_from_pricecharting(liquidity_info, attributes)

        if not pricecharting_price:
            # print(
            #     f"Failed to get pricing information for: {asset['title']}\nhttps://courtyard.io/asset/{asset['proof_of_integrity']}")
            continue

        if compare_prices(pricecharting_price, courtyard_price):
            send_results_to_discord(
                card_name=card_name,
                card_img=card_img,
                pricecharting_price=pricecharting_price,
                courtyard_price=courtyard_price,
                pricecharting_url=pricecharting_url,
                courtyard_url=courtyard_url,
                volume=volume
            )

    latest_card_serial = flatten_attributes(assets[0]['attributes'])['Serial']
    if latest_card_serial != last_processed_serial:
        update_github_repo_variable(latest_card_serial)


def main(*argv):
    if len(argv) > 1 and argv[1]:
        driver(argv[1])
    else:
        driver()


if __name__ == "__main__":
    main(sys.argv)
