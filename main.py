import csv
from dataclasses import dataclass
from typing import Dict

import requests
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware
from web3.types import BlockData, TxData

base_url = 'https://api.ftnscan.com/api'
ftn_rpc = 'https://rpc1.bahamut.io'

web3 = Web3(Web3.HTTPProvider(ftn_rpc))
web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)


@dataclass
class Wallet:
    address: str
    exchange_name: str


exchange_hot_wallets: Dict[str, Wallet] = {
    '0x04950aaac4f1896a0385c85415904677ce770303': Wallet('0x04950aaac4f1896a0385c85415904677ce770303', 'MEXC'),
    '0xc21a1d213f64fedea3415737cce2be37eb59be81': Wallet('0xc21a1d213f64fedea3415737cce2be37eb59be81', 'FASTEX'),
    '0x0d0707963952f2fba59dd06f2b425ace40b492fe': Wallet('0x0d0707963952f2fba59dd06f2b425ace40b492fe', 'GATE.IO'),
    '0x97b9d2102a9a65a26e1ee82d59e42d1b73b68689': Wallet('0x97b9d2102a9a65a26e1ee82d59e42d1b73b68689', 'BITGET'),
    '0x74b0e133bee3384dfcfa60b31d85d8e2062de811': Wallet('0x74b0e133bee3384dfcfa60b31d85d8e2062de811', 'BINGX')
}
transit_wallets: Dict[str, Wallet] = {}

contract_address = '0x0ca83dd56af172a1e04b667d6e64446d0b88c4a4'
TELEGRAM_BOT_TOKEN = '7663401015:AAEnpvk5PoMw1KXGWXnehfZUlvZ_PvPG7aE'
TELEGRAM_CHAT_IDS = ['717664582', '508884173', '667789228']


def get_all_transits_wallets(hot_wallet: str, exchange_name: str):
    page = 1
    params = {
        'module': 'account',
        'action': 'txlist',
        'address': hot_wallet,
        'sort': 'desc',
        'offset': 10000
    }
    while True:
        print(page)
        params['page'] = page
        response = requests.get(base_url, params=params).json()
        txs = response['result']
        for tx in txs:
            if tx['to'].lower() == hot_wallet.lower() and tx['to'].lower() not in transit_wallets:
                transit_wallets[tx['from'].lower()] = Wallet(tx['from'].lower(), exchange_name)
        page += 1
        if len(txs) < 10000:
            break


def get_amount_of_ftn(tx_hash):
    amount = 0
    logs = requests.get("https://api.ftnscan.com/api", params={
        'module': 'transaction',
        'action': 'gettxinfo',
        'txhash': tx_hash
    }).json().get('result').get('logs')
    for log in logs:
        if log.get('topics')[0].startswith('0xddf252ad'):
            amount = int(log.get('data'), 16) / 10 ** 18
    return amount


def handle_new_block(block: BlockData):
    transactions = block['transactions']
    for tx in transactions:

        if tx['to'].lower() in transit_wallets:  # Если в транзакции идет деп на транзитный кошелек
            if web3.from_wei(tx['value'], 'ether') > 5000:
                message = generate_message(tx, 1)
                send_telegram_notification(message)

        # Если идет деп на горячий кошелек, то добваляем его в список транзитных
        elif tx['to'].lower() in exchange_hot_wallets and tx['from'].lower() not in transit_wallets:
            if web3.from_wei(tx['value'], 'ether') > 5000:
                transit_wallets[tx['from'].lower()] = Wallet(tx['from'].lower(),
                                                             exchange_hot_wallets[tx['to'].lower()].exchange_name)
                message = generate_message(tx, 2)
                send_telegram_notification(message)

        elif tx['to'].lower() == contract_address:
            if tx['input'].startswith('0x98dcef71'):
                value = get_amount_of_ftn(f'0x{tx["hash"].hex()}')
                if value > 5000:
                    message = generate_message(tx, 3, value)
                    send_telegram_notification(message)
                else:
                    pass

        else:
            pass


def send_telegram_notification(message):
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        response = requests.post(url, data=payload)
        if response.status_code != 200:
            print(f"Ошибка при отправке в Telegram: {response.text}")


def save_transit_wallets(transit_wallets: Dict[str, Wallet], file_name: str):
    with open(file_name, 'w') as f:
        writer = csv.DictWriter(f, fieldnames=['address', 'exchange_name'])
        writer.writeheader()

        for _, wallet in transit_wallets.items():
            writer.writerow({'address': wallet.address, 'exchange_name': wallet.exchange_name})


def generate_message(tx: TxData, type_of_message: int, value=0) -> str:
    if type_of_message == 1:
        message = (
            f"🔔 <b>Депозит на промежуточный кошелек {transit_wallets[tx['to'].lower()].exchange_name}</b>\n"
            f"Сумма: {float(web3.from_wei(tx['value'], 'ether')):.2f} FTN\n"
            f"Ссылка: <a href='https://www.ftnscan.com/tx/0x{tx['hash'].hex()}'>Посмотреть</a>"
        )
    elif type_of_message == 2:
        message = (
            f"💸 <b>Депозит на кошелек биржи {exchange_hot_wallets[tx['to'].lower()].exchange_name}</b>\n"
            f"Сумма: {float(web3.from_wei(tx['value'], 'ether')):.2f} FTN\n"
            f"Ссылка: <a href='https://www.ftnscan.com/tx/0x{tx['hash'].hex()}'>Посмотреть</a>"
        )
    elif type_of_message == 3:
        message = (
            f"⚡️ <b>С контракта выведены FTN</b>\n"
            f"Сумма: {float(web3.from_wei(tx['value'], 'ether'))}:.2f FTN\n"
            f"Ссылка: <a href='https://www.ftnscan.com/tx/0x{tx['hash'].hex()}'>Посмотреть</a>"
        )
    return message


def main():
    send_telegram_notification("Собираю список транзитных кошельков...")
    # Сбор транзитных кошельков
    for k, v in exchange_hot_wallets.items():
        get_all_transits_wallets(k, v.exchange_name)

    for address in exchange_hot_wallets.keys():
        transit_wallets.pop(address.lower(), None)

    save_transit_wallets(transit_wallets, file_name='wallets.csv')
    send_telegram_notification(f"Сбор транзитных кошельков окончен. Обнаружено {len(transit_wallets)} шт")
    send_telegram_notification("Скринер запущен ✅")

    # Получение последнего блока
    last_block = web3.eth.block_number
    while True:
        current_block_number = web3.eth.block_number
        if current_block_number == last_block:
            pass
        else:

            last_block = current_block_number
            block = web3.eth.get_block(current_block_number, full_transactions=True)
            print(f"Current block number: {current_block_number} | Обработка")
            # Обработка последнего блока
            handle_new_block(block)


main()
