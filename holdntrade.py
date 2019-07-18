#!/usr/bin/python
import configparser
import datetime
import inspect
import logging
import os
import pickle
import random
import smtplib
import socket
import sys
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler

import ccxt
import requests

# ------------------------------------------------------------------------------

sell_price = 0
sell_orders = []
buy_price = 0
buy_orders = []
curr_buy_order = None
curr_buy_order_size = 0
reset_counter = 0
loop = False
auto_conf = False
email_only = False
email_sent = 0
started = datetime.datetime.utcnow().replace(microsecond=0)
stats = None
no_recall = ['nsufficient', 'too low', 'not_enough_free_balance', 'margin_below']

# ------------------------------------------------------------------------------


class ExchangeConfig:
    """
    Holds the configuration read from separate .txt file.
    """
    def __init__(self, filename: str):

        config = configparser.RawConfigParser()
        config.read(filename + ".txt")

        try:
            props = dict(config.items('config'))
            self.bot_instance = filename
            self.bot_version = "1.13.0"
            self.exchange = props['exchange'].strip('"').lower()
            self.api_key = props['api_key'].strip('"')
            self.api_secret = props['api_secret'].strip('"')
            self.test = bool(props['test'].strip('"').lower() == 'true')
            self.pair = props['pair'].strip('"')
            self.symbol = props['symbol'].strip('"')
            self.order_crypto_min = float(props['order_crypto_min'].strip('"'))
            self.satoshi_factor = 0.00000001
            self.change = abs(float(props['change'].strip('"')))
            self.quota = abs(int(props['quota'].strip('"')))
            if self.quota < 1:
                self.quota = 1
            self.spread_factor = abs(float(props['spread_factor'].strip('"')))
            self.auto_leverage = bool(props['auto_leverage'].strip('"').lower() == 'true')
            self.auto_leverage_overdrive = bool(props['auto_leverage_overdrive'].strip('"').lower() == 'true')
            self.leverage_default = abs(float(props['leverage_default'].strip('"')))
            self.leverage_low = abs(float(props['leverage_low'].strip('"')))
            self.leverage_high = abs(float(props['leverage_high'].strip('"')))
            self.leverage_overdrive = abs(float(props['leverage_overdrive'].strip('"')))
            self.mm_floor = abs(float(props['mm_floor'].strip('"')))
            self.mm_ceil = abs(float(props['mm_ceil'].strip('"')))
            currency = self.pair.split("/")
            self.base = currency[0]
            self.quote = currency[1]
            self.send_emails = bool(props['send_emails'].strip('"').lower() == 'true')
            self.recipient_addresses = props['recipient_addresses'].strip('"').replace(' ', '').split(",")
            self.sender_address = props['sender_address'].strip('"')
            self.sender_password = props['sender_password'].strip('"')
            self.mail_server = props['mail_server'].strip('"')
        except (configparser.NoSectionError, KeyError):
            raise SystemExit('invalid configuration for ' + filename)


class OpenOrdersSummary:
    """
    Creates and holds an open orders summary
    """
    def __init__(self, open_orders):
        self.orders = []
        self.sell_orders = []
        self.buy_orders = []
        self.total_sell_order_value = 0
        self.total_buy_order_value = 0

        for oo in open_orders:
            o = Order(oo)
            self.orders.append(o)
            if o.side == 'sell':
                if conf.exchange == 'kraken':
                    self.total_sell_order_value += o.amount * o.price
                else:
                    self.total_sell_order_value += o.amount
                self.sell_orders.append(o)
            elif o.side == 'buy':
                if conf.exchange == 'kraken':
                    self.total_buy_order_value += o.amount * o.price
                else:
                    self.total_buy_order_value += o.amount
                self.buy_orders.append(o)
            else:
                log.error(inspect.stack()[1][3], ' ?!?')

        self.sell_orders = sorted(self.sell_orders, key=lambda order: order.price, reverse=True)  # desc
        self.buy_orders = sorted(self.buy_orders, key=lambda order: order.price, reverse=True)  # desc


class Order:
    """
    Creates and holds the relevant data of an order
    """
    def __init__(self, order):
        self.id = order['id']
        self.price = order['price']
        self.amount = order['amount']
        self.side = order['side']
        self.datetime = order['datetime']

    def __str__(self):
        return "{} order id: {}, price: {}, amount: {}, created: {}".format(self.side, self.id, self.price,
                                                                            self.amount, self.datetime)


class Stats:
    """
    Holds the daily statistics in a ring memory (today plus the previous two)
    """
    def __init__(self, day_of_year: int, data: dict):
        self.days = []
        self.add_day(day_of_year, data)

    def add_day(self, day_of_year: int, data: dict):
        existing = self.get_day(day_of_year)
        if existing is None:
            data['day'] = day_of_year
            if len(self.days) > 2:
                self.days = sorted(self.days, key=lambda data: data['day'], reverse=True)  # desc
                self.days.pop()
            self.days.append(data)

    def get_day(self, day_of_year: int):
        matched = filter(lambda element: element['day'] == day_of_year, self.days)
        if matched is not None:
            for day in matched:
                return day
        return None


def function_logger(console_level: int, filename: str, file_level: int = None):
    function_name = inspect.stack()[1][3]
    logger = logging.getLogger(function_name)
    # By default log all messages
    logger.setLevel(logging.DEBUG)

    # StreamHandler logs to console
    ch = logging.StreamHandler()
    ch.setLevel(console_level)
    ch_format = logging.Formatter('%(message)s')
    ch.setFormatter(ch_format)
    logger.addHandler(ch)

    if file_level is not None:
        fh = RotatingFileHandler("{}.log".format(filename), mode='a', maxBytes=5 * 1024 * 1024, backupCount=4,
                                 encoding=None, delay=0)
        fh.setLevel(file_level)
        fh_format = logging.Formatter('%(asctime)s - %(lineno)4d - %(levelname)-8s - %(message)s')
        fh.setFormatter(fh_format)
        logger.addHandler(fh)

    return logger


def buy_executed(price: float, amount: int):
    """
    Check if the most recent buy order has been executed.
    input: current price and amount to trade (Current Balance / quota)
    output: if the most recent buy order is still open,
    the output is print statements containing the amount were trying to buy for which price.
    Else if the order is closed, we follow with the followup function and createbuyorder and
    pass on the variables we got from input.
    """
    global curr_buy_order_size
    global buy_orders

    if curr_buy_order is None:
        status = 'closed'
        log.info('Closed inexisting compensation order')
    else:
        status = fetch_order_status(curr_buy_order.id)
    log.debug('-------------------------------')
    log.debug(time.ctime())
    if status == 'open':
        log.debug('Open Buy Order! Amount: %d @ %.1f', int(curr_buy_order_size), float(buy_price))
        log.debug('Current Price: %.1f', price)
    elif status in ['closed', 'canceled']:
        log.info('Buy executed, starting follow up')
        if curr_buy_order in buy_orders:
            buy_orders.remove(curr_buy_order)
        # default case: use amount of last (previous) buy order for next sell order
        # else last buy was compensation order: use same amount for next sell order as the buy order to be created next
        last_buy_size = curr_buy_order_size if curr_buy_order is not None else amount
        if create_buy_order(price, amount):
            create_sell_order(last_buy_size)
        else:
            log.warning('Resetting')
            init_orders(True, False)
    else:
        log.warning('You should not be here, order state: %s', status)


def sell_executed(price: float, amount: int):
    """
    Check if any of the open sell orders has been executed.
    input: current price and amount to trade (Current Balance / quota)
    output: loop through all open sell orders and check if one has been executed. If no, exit with print statement.
    Else if it has been executed, remove the order from the list of open orders,
    cancel it on Bitmex and create a new buy order.
    """
    global sell_orders

    for order in sell_orders:
        time.sleep(0.5)
        status = fetch_order_status(order.id)
        if status == 'open':
            log.debug('Sell still open')
        elif status in ['closed', 'canceled']:
            if order in sell_orders:
                sell_orders.remove(order)
            log.info('Sell executed')
            adjust_leverage()
            if not sell_orders:
                create_divided_sell_order()
            cancel_current_buy_order()
            if not create_buy_order(price, amount):
                log.warning('Resetting')
                init_orders(True, False)
        else:
            log.warning('You should not be here, order state: %s', status)


def cancel_current_buy_order():
    """
    Cancels the current buy order
    """
    global curr_buy_order

    if curr_buy_order is not None:
        cancel_order(curr_buy_order)
        if curr_buy_order in buy_orders:
            buy_orders.remove(curr_buy_order)
        log.info('Canceled current %s', str(curr_buy_order))
        curr_buy_order = None if not buy_orders else buy_orders[0]


def create_sell_order(fixed_order_size: int = None):
    """
    Loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.
    """
    global sell_price
    global curr_buy_order_size
    global sell_orders

    order_size = curr_buy_order_size if fixed_order_size is None else fixed_order_size

    available = get_balance()['free'] * sell_price
    if available < order_size:
        # sold out - the main loop will re-init if there are no other sell orders open
        log.warning('Not executing sell order over %d (only %d left)', order_size, available)
        return

    try:
        if not is_order_below_limit(order_size, sell_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = exchange.create_limit_sell_order(conf.pair, order_size, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                new_order = exchange.create_limit_sell_order(conf.pair, to_crypto_amount(order_size, rate), sell_price,
                                                             {'leverage': conf.leverage_default})
            elif conf.exchange == 'liquid':
                rate = get_current_price()
                new_order = exchange.create_limit_sell_order(conf.pair, to_crypto_amount(order_size, rate), sell_price,
                                                             {'leverage_level': conf.leverage_default,
                                                              'funding_currency': conf.base})
            order = Order(new_order)
            sell_orders.append(order)
            log.info('Created %s', str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in no_recall):
            log.error('Insufficient funds - not selling %d', order_size)
            return
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sell_price = round(get_current_price() * (1 + conf.change))
        return create_sell_order(fixed_order_size)


def create_divided_sell_order():
    """
    Loop that starts after buy order is executed and sends sell order to exchange
    as well as appends the orderID to the sell_orders list.
    """
    global sell_orders
    global sell_price

    try:
        used_bal = get_used_balance()
        amount = round(used_bal / conf.quota)

        if not is_order_below_limit(amount, sell_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
                new_order = exchange.create_limit_sell_order(conf.pair, amount, sell_price)
            elif conf.exchange == 'kraken':
                rate = get_current_price()
                new_order = exchange.create_limit_sell_order(conf.pair, to_crypto_amount(amount, rate), sell_price,
                                                             {'leverage': conf.leverage_default})
            elif conf.exchange == 'liquid':
                rate = get_current_price()
                new_order = exchange.create_limit_sell_order(conf.pair, to_crypto_amount(amount, rate), sell_price,
                                                             {'leverage_level': conf.leverage_default,
                                                              'funding_currency': conf.base})
            order = Order(new_order)
            sell_orders.append(order)
            log.info('Created %s', str(order))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in no_recall):
            log.error('Insufficient funds - not selling %d', amount)
            return
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sell_price = round(get_current_price() * (1 + conf.change))
        return create_divided_sell_order()


def fetch_order_status(order_id: str):
    """
    Fetches the status of an order
    input: id of an order
    output: status of the order (open, closed)
    """
    try:
        return exchange.fetch_order_status(order_id)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return fetch_order_status(order_id)


def cancel_order(order: Order):
    """
    Cancels an order
    """
    try:
        if order is not None:
            status = exchange.fetch_order_status(order.id)
            if status == 'open':
                exchange.cancel_order(order.id)
            else:
                log.warning('Order to be canceled %s was in state %s', order.id, status)

    except ccxt.OrderNotFound as error:
        log.error('Order to be canceled not found %s %s', order.id, str(error.args))
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return cancel_order(order)


def create_buy_order(price: float, amount: int):
    """
    Creates a buy order and sets the values as global ones. Used by other functions.
    :param price current price of crypto
    :param amount the order volume
    output: calculate the price to get long (price + change) and to get short (price - change).
    In addition set the current orderID and current order size as global values.
    If the amount is below the order limit or there is not enough margin and there are open sell orders, the function
    is going to sleep, allowing sell orders to be filled - afterwards the amount is recalculated and the function calls
    itself with the new amount
    """
    global sell_price
    global buy_price
    global curr_buy_order_size
    global curr_buy_order
    global buy_orders

    buy_price = round(price * (1 - conf.change))
    sell_price = round(price * (1 + conf.change))
    curr_buy_order_size = amount
    curr_price = get_current_price()

    try:
        if not is_order_below_limit(amount, buy_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = exchange.create_limit_buy_order(conf.pair, amount, buy_price)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_limit_buy_order(conf.pair, to_crypto_amount(amount, curr_price), buy_price,
                                                            {'leverage': conf.leverage_default, 'oflags': 'fcib'})
            elif conf.exchange == 'liquid':
                new_order = exchange.create_limit_buy_order(conf.pair, to_crypto_amount(amount, curr_price), buy_price,
                                                            {'leverage_level': conf.leverage_default,
                                                             'funding_currency': conf.base})
            order = Order(new_order)
            log.info('Created %s', str(order))
            curr_buy_order = order
            buy_orders.append(order)
            return True
        if sell_orders:
            log.info('Could not create buy order, waiting for a sell order to be realised')
            return delay_buy_order(curr_price, price)

        log.warning('Could not create buy order over %d and there are no open sell orders, reset required', amount)
        return False

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in no_recall):
            if sell_orders:
                log.info(
                    'Could not create buy order over %s, insufficient margin, waiting for a sell order to be realised',
                    str(amount))
                return delay_buy_order(curr_price, price)

            log.warning('Could not create buy order over %d, insufficient margin', amount)
            return False
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_buy_order(update_price(curr_price, price), amount)


def delay_buy_order(crypto_price: float, price: float):
    """
    Delays the creation of a buy order, allowing sell orders to be filled - afterwards the amount is recalculated and
    the function calls create_buy_order with the current price and the new amount
    :param crypto_price: the crypto rate with which price was calculated
    :param price: the price of the original buy order to be created
    """
    sleep_for(90, 180)
    daily_report()
    new_amount = round(get_balance()['free'] / conf.quota * get_current_price())  # recalculate order size
    if is_order_below_limit(new_amount, update_price(crypto_price, price)):
        if conf.auto_leverage and conf.auto_leverage_overdrive:
            boost_leverage()
            new_amount = round(get_balance()['free'] / conf.quota * get_current_price())  # recalculate order size
        elif conf.auto_leverage:
            adjust_leverage()
            new_amount = round(get_balance()['free'] / conf.quota * get_current_price())  # recalculate order size
    return create_buy_order(update_price(crypto_price, price), new_amount)


def create_market_sell_order(amount_crypto: float):
    """
    Creates a market sell order and sets the values as global ones. Used to compensate margins above 50%.
    input: amount_crypto to be sold to reach 50% margin
    """
    global buy_price
    global sell_price
    global sell_orders

    cur_price = get_current_price()
    amount = round(amount_crypto * cur_price)
    buy_price = round(cur_price * (1 - conf.change))
    sell_price = round(cur_price * (1 + conf.change))

    try:
        if not is_crypto_amount_below_limit(amount_crypto):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = exchange.create_market_sell_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_market_sell_order(conf.pair, amount_crypto, {'leverage': conf.leverage_default})
            elif conf.exchange == 'liquid':
                new_order = exchange.create_market_sell_order(conf.pair, amount,
                                                              {'leverage_level': conf.leverage_default})
            order = Order(new_order)
            log.info('Created market %s', str(order))
            sell_orders.append(order)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in no_recall):
            log.error('Insufficient balance/funds - not selling %d', amount)
            return
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_sell_order(amount_crypto)


def create_market_buy_order(amount_crypto: float):
    """
    Creates a market buy order and sets the values as global ones. Used to compensate margins below 50%.
    input: amount_crypto to be bought to reach 50% margin
    """
    global buy_price
    global sell_price
    global curr_buy_order

    cur_price = get_current_price()
    amount = round(amount_crypto * cur_price)
    buy_price = round(cur_price * (1 - conf.change))
    sell_price = round(cur_price * (1 + conf.change))

    try:
        if not is_order_below_limit(amount, cur_price):
            if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
                new_order = exchange.create_market_buy_order(conf.pair, amount)
            elif conf.exchange == 'kraken':
                new_order = exchange.create_market_buy_order(conf.pair, amount_crypto,
                                                             {'leverage': conf.leverage_default, 'oflags': 'fcib'})
            elif conf.exchange == 'liquid':
                new_order = exchange.create_market_buy_order(conf.pair, amount_crypto,
                                                             {'leverage_level': conf.leverage_default,
                                                              'funding_currency': conf.base})
            order = Order(new_order)
            log.info('Created market %s', str(order))
            curr_buy_order = None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if "not_enough_free" or "free_margin_below" in str(error.args):
            log.error('Not enough free margin/balance %s %s', type(error).__name__, str(error.args))
            return

        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return create_market_buy_order(amount_crypto)


def get_margin_leverage():
    """
    Fetch the leverage
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return exchange.fetch_balance()['info'][0]['marginLeverage']
        if conf.exchange == 'kraken':
            return float(exchange.private_post_tradebalance()['result']['ml'])
        if conf.exchange == 'liquid':
            # TODO poi = get_position_info()
            log.error("get_margin_leverage() not yet implemented for %s", conf.exchange)
            return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_leverage()


def get_wallet_balance():
    """
    Fetch the wallet balance in crypto
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return exchange.fetch_balance()['info'][0]['walletBalance'] * conf.satoshi_factor
        if conf.exchange == 'kraken':
            asset = conf.base if conf.base != 'BTC' else 'XBt'
            return float(exchange.private_post_tradebalance({'asset': asset})['result']['tb'])
        if conf.exchange == 'liquid':
            result = exchange.private_get_accounts_balance()
            if result is not None:
                for b in result:
                    if b['currency'] == conf.base:
                        return float(b['balance'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_wallet_balance()


def get_balance():
    """
    Fetch the balance in crypto.
    output: balance (used,free,total)
    """
    try:
        if conf.exchange != 'liquid':
            bal = exchange.fetch_balance()[conf.base]
            if bal['used'] is None:
                bal['used'] = 0
            if bal['free'] is None:
                bal['free'] = 0
            return bal

        bal = None
        result = exchange.private_get_trading_accounts()
        if result is not None:
            for acc in result:
                if acc['currency_pair_code'] == conf.symbol and float(acc['margin']) > 0:
                    bal = {'used': float(acc['margin']), 'free': float(acc['free_margin']),
                           'total': float(acc['equity'])}
        if bal is None:
            # no position => return wallet balance
            result = exchange.private_get_accounts_balance()
            if result is not None:
                for b in result:
                    if b['currency'] == conf.base:
                        bal = {'used': 0, 'free': float(b['balance']), 'total': float(b['balance'])}
        return bal

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_balance()


def get_used_balance():
    """
    Fetch the used balance in fiat.
    output: balance
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            return exchange.private_get_position()[0]['currentQty']
        if conf.exchange == 'kraken':
            result = exchange.private_post_tradebalance()['result']
            return round(float(result['e']) - float(result['mf']))
        if conf.exchange == 'liquid':
            return round(get_balance()['used'] * get_current_price())

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_used_balance()


def get_net_deposits():
    """
    Get deposits and withdraws to calculate the net deposits in crypto.
    return: net deposits
    """
    try:
        currency = conf.base if conf.base != 'BTC' else 'XBt'
        if conf.exchange == 'bitmex':
            result = exchange.private_get_user_wallet({'currency': currency})
            return (result['deposited'] - result['withdrawn']) * conf.satoshi_factor
        if conf.exchange == 'kraken':
            net_deposits = 0
            deposits = exchange.fetch_deposits(conf.base)
            for deposit in deposits:
                net_deposits += deposit['amount']
            ledgers = exchange.private_post_ledgers({'asset': currency, 'type': 'withdrawal'})['result']['ledger']
            for withdrawal_id in ledgers:
                net_deposits += float(ledgers[withdrawal_id]['amount'])
            return net_deposits
        log.error("get_net_deposit() not yet implemented for %s", conf.exchange)
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_net_deposits()


def get_position_info():
    """
    Fetch position information
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            response = exchange.private_get_position()
            if response and response[0] and response[0]['avgEntryPrice']:
                return response[0]
            return None
        if conf.exchange == 'kraken':
            log.error("get_position_info() not yet implemented for kraken")
            return None
        if conf.exchange == 'liquid':
            response = exchange.private_get_trading_accounts()
            for pos in response:
                if pos['currency_pair_code'] == conf.symbol and pos['funding_currency'] == conf.base and \
                        float(pos['margin']) > 0:
                    return pos
            return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_position_info()


def compensate():
    """
    Approaches the margin used towards 50% by selling or buying the difference to market price
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase', 'liquid']:
            bal = get_balance()
        elif conf.exchange == 'kraken':
            bal = exchange.private_post_tradebalance({'asset': conf.base})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
            bal['used'] = float(bal['m'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return compensate()

    used = float(100 - (bal['free'] / bal['total']) * 100)
    if used < 40 or used > 60:
        amount_crypto = float(bal['total'] / 2 - bal['used'])
        if amount_crypto > 0:
            log.info("Need to buy {} {} in order to reach 50% margin".format(amount_crypto, conf.base))
            create_market_buy_order(amount_crypto)
        else:
            log.info("Need to sell {} {} in order to reach 50% margin".format(abs(amount_crypto), conf.base))
            create_market_sell_order(abs(amount_crypto))
    return


def spread(market_price: float):
    """
    Checks if the difference between the highest buy order price and the market price is bigger than spread_factor times
    change and the difference of the lowest sell order to the market price is bigger spread_factor times change
    If so, then the highest buy order is canceled and a new buy and sell order are created with the configured offset
    to the market price
    """
    if buy_orders and sell_orders:
        highest_buy_order = sorted(buy_orders, key=lambda order: order.price, reverse=True)[0]
        if highest_buy_order.price < market_price * (1 - conf.change * conf.spread_factor):
            lowest_sell_order = sorted(sell_orders, key=lambda order: order.price)[0]
            if lowest_sell_order.price > market_price * (1 + conf.change * conf.spread_factor):
                log.info("Orders above spread tolerance min sell: %f max buy: %f current rate: %f",
                         lowest_sell_order.price, highest_buy_order.price, market_price)
                log.info("Canceling highest %s", str(highest_buy_order))
                cancel_order(highest_buy_order)
                if create_buy_order(market_price, highest_buy_order.amount):
                    create_sell_order()


def get_margin_balance():
    """
    Fetches the margin balance in fiat (free and total)
    return: balance in fiat
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            bal = exchange.fetch_balance()[conf.base]
        elif conf.exchange == 'kraken':
            bal = exchange.private_post_tradebalance({'asset': conf.base})['result']
            bal['free'] = float(bal['mf'])
            bal['total'] = float(bal['e'])
        elif conf.exchange == 'liquid':
            bal = get_balance()
        return bal

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_margin_balance()


def calculate_used_margin_percentage(bal=None):
    """
    Calculates the used margin percentage
    """
    if bal is None:
        bal = get_margin_balance()
        if bal['total'] <= 0:
            return 0
    return float(100 - (bal['free'] / bal['total']) * 100)


def calc_avg_entry_price(open_orders: [Order]):
    """"
    Calculates the average entry price of the remaining amount of all open orders (required for kraken only)
    :param open_orders: [Order]
    """
    total_amount = 0
    total_price = 0
    for o in open_orders:
        total_amount += o.amount
        total_price += o.price * o.amount
    if total_amount > 0:
        return total_price / total_amount
    return 0


def get_current_price():
    """
    Fetch the current crypto price
    output: last bid price
    """
    sleep_for(4, 6)
    try:
        return exchange.fetch_ticker(conf.pair)['bid']

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        return get_current_price()


def update_price(origin_price: float, price: float):
    """
    Update the price by considering the old and current price
    :param origin_price:
    :param price:
    :return: price
    """
    return (get_current_price() / origin_price) * price


def init_orders(force_close: bool, auto_conf: bool):
    """
    Initialize existing orders or remove all pending ones
    output True if loaded and False if compensate margin is necessary
    :param force_close: close all orders/positions (reset)
    :param auto_conf: load all orders and keep position
    :return:
    """
    global sell_price
    global sell_orders
    global curr_buy_order_size
    global curr_buy_order
    global buy_orders
    global buy_price
    global reset_counter

    if force_close:
        reset_counter += 1

    try:
        init = ''
        if auto_conf:
            log.warning("Bot was resurrected by hades")

        # Handle open orders
        oos = get_open_orders()

        log.info("Used margin: {:>17.2f}%".format(calculate_used_margin_percentage()))
        print_position_info(oos)

        if oos.orders:
            log.info("Value of buy orders {}: {:>2}".format(conf.base, int(oos.total_buy_order_value)))
            log.info("Value of sell orders {}: {:>1}".format(conf.base, int(oos.total_sell_order_value)))
            log.info("No. of buy orders: {:>8}".format(len(oos.buy_orders)))
            log.info("No. of sell orders: {:>7}".format(len(oos.sell_orders)))
            log.info('-------------------------------')

            if not force_close and not auto_conf:
                init = input('There are open orders! Would you like to load them? (y/n) ')
            if not force_close and (auto_conf or init.lower() in ['y', 'yes']):
                return load_existing_orders(oos)

            log.info('Unrealised PNL: %s %s', str(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor), conf.base)
            if force_close:
                cancel_orders(oos.orders)
            else:
                clear_position = input('There is an open ' + conf.base + ' position! Would you like to close it? (y/n) ')
                if clear_position.lower() in ['y', 'yes']:
                    cancel_orders(oos.orders)
                    close_position(conf.symbol)
                else:
                    compensate_position = input('Would you like to compensate to 50%? (y/n) ')
                    if compensate_position.lower() in ['n', 'no']:
                        # No "compensate" wanted
                        return True

        # Handle open positions if no orders are open
        elif not force_close and not auto_conf and get_open_position(conf.symbol) is not None:
            msg = 'There is an open ' + conf.base + ' position!\nUnrealised PNL: {:.8f} ' + conf.base + \
                  '\nWould you like to close it? (y/n) '
            init = input(msg.format(get_unrealised_pnl(conf.symbol) * conf.satoshi_factor))
            if init.lower() in ['y', 'yes']:
                close_position(conf.symbol)

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return init_orders(force_close, auto_conf)

    else:
        del oos
        log.info('Initialization complete')
        # compensate
        return False


def load_existing_orders(oos: OpenOrdersSummary):
    global sell_orders, sell_price, buy_orders, curr_buy_order, buy_price, curr_buy_order_size
    if oos.sell_orders:
        sell_orders = oos.sell_orders
        sell_price = sell_orders[0].price  # lowest if several
    if oos.buy_orders:
        buy_orders = oos.buy_orders
        curr_buy_order = buy_orders[-1]  # highest if several
        buy_price = curr_buy_order.price
        curr_buy_order_size = curr_buy_order.amount
    # All sell orders executed
    if not oos.sell_orders:
        sell_price = round(get_current_price() * (1 + conf.change))
        create_sell_order()
    # All buy orders executed
    elif not oos.buy_orders:
        create_buy_order(get_current_price(), round(get_balance()['free'] / conf.quota * get_current_price()))
    del oos
    log.info('Initialization complete (using existing orders)')
    # No "compensate" necessary
    return True


def cancel_orders(orders: [Order]):
    """
    Close a list of orders
    :param orders: [Order]
    """
    try:
        for o in orders:
            log.debug('Cancel %s', str(o))
            status = exchange.fetch_order_status(o.id)
            if status == 'open':
                exchange.cancel_order(o.id)
            else:
                log.warning('Cancel %s was in state %s', str(o), status)

    except ccxt.OrderNotFound as error:
        log.error('Cancel %s not found : %s', str(o), str(error.args))
        return
    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return cancel_orders(orders)


def close_position(symbol: str):
    """
    Close any open position
    """
    try:
        log.info('close position %s', symbol)
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            exchange.private_post_order_closeposition({'symbol': symbol})
        elif conf.exchange == 'kraken':
            exchange.create_market_sell_order(conf.pair, 0.0, {'leverage': conf.leverage_default})
        elif conf.exchange == 'liquid':
            exchange.private_put_trades_close_all()

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        # no retry in case of "no volume to close position" (kraken specific error)
        if "volume to close position" in str(error.args):
            return
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return close_position(symbol)


def get_open_position(symbol: str):
    """
    Get all open positions
    :return: positions
    """
    try:
        if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
            for p in exchange.private_get_position():
                if p['isOpen'] and p['symbol'] == symbol:
                    return p
        elif conf.exchange == 'kraken':
            a = exchange.private_post_openpositions()
            if a['result'] == 'success':
                for p in a['openPositions']:
                    if p['symbol'] == symbol:
                        return p
        elif conf.exchange == 'liquid':
            trades = exchange.private_get_trades({'status': 'open'})
            for model in trades['models']:
                if model['currency_pair_code'] == conf.pair:
                    return model
        return None

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_open_position(symbol)


def get_open_orders():
    """
    Gets all open orders
    :return: OpenOrdersSummary
    """
    try:
        return OpenOrdersSummary(exchange.fetch_open_orders(conf.pair, since=None, limit=None, params={}))

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_open_orders()


def get_unrealised_pnl(symbol: str):
    """
    Returns the unrealised pnl for the requested currency
    :param symbol:
    :return: float
    """
    try:
        if get_open_position(symbol) is not None:
            return float(get_open_position(symbol)['unrealisedPnl'])
        return 0.0

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_unrealised_pnl(symbol)


def print_position_info(oos: OpenOrdersSummary):
    if conf.exchange in ['bitmex', 'binance', 'bitfinex', 'coinbase']:
        sleep_for(1, 2)
        poi = get_position_info()
        if poi:
            log.info("Position {}: {:>13}".format(conf.quote, poi['currentQty']))
            log.info("Entry price: {:>16.1f}".format(poi['avgEntryPrice']))
            log.info("Market price: {:>15.1f}".format(poi['markPrice']))
            log.info("Liquidation price: {:>10.1f}".format(poi['liquidationPrice']))
            del poi
        else:
            log.info("Available balance is {}: {:>3} ".format(conf.base , get_balance()['free']))
            log.info("No position found, I will create one for you")
            return False
    elif conf.exchange == 'kraken':
        log.info("Position {}: {:>13}".format(conf.quote, get_used_balance()))
        log.info("Entry price: {:>16.1f}".format(calc_avg_entry_price(oos.orders)))
        log.info("Market price: {:>15.1f}".format(get_current_price()))
    elif conf.exchange == 'liquid':
        poi = get_position_info()
        if float(poi['position']) > 0:
            log.info("Position {}: {:>13.2f}".format(conf.base, float(poi['position'])))
        else:
            log.info("Available balance is {}: {:>3} ".format(conf.base, get_balance()['free']))
            log.info("No position found, I will create one for you")
            return False
    if not oos.orders:
        log.info("No open orders")


def connect_to_exchange(conf: ExchangeConfig):
    """
    Connects to the exchange.
    :param conf: ExchangeConfig
    :return: exchange
    """
    exchanges = {'binance': ccxt.binance,
                 'bitfinex': ccxt.bitfinex,
                 'bitmex': ccxt.bitmex,
                 'coinbase': ccxt.coinbase,
                 'kraken': ccxt.kraken,
                 'liquid': ccxt.liquid}

    exchange = exchanges[conf.exchange]({
        'enableRateLimit': True,
        'apiKey': conf.api_key,
        'secret': conf.api_secret,
        # 'verbose': True,
    })

    # pprint(dir(exchange))

    if hasattr(conf, 'test') & conf.test:
        if 'test' in exchange.urls:
            exchange.urls['api'] = exchange.urls['test']
        else:
            raise SystemExit('Test not supported by %s', conf.exchange)

    log.info('Connecting to %s', conf.exchange)
    return exchange


def sleep_for(greater: int, less: int):
    seconds = round(random.uniform(greater, less), 3)
    time.sleep(seconds)


def is_order_below_limit(amount: int, price: float):
    return is_crypto_amount_below_limit(abs(amount / price))


def is_crypto_amount_below_limit(amount_crypto: float):
    if abs(amount_crypto) < conf.order_crypto_min:
        log.info('Per order volume below limit: %f', abs(amount_crypto))
        return True
    return False


def to_crypto_amount(amount: int, price: float):
    return round(amount / price, 8)


def write_control_file(filename: str):
    with open(filename + '.pid', 'w') as f:
        f.write(str(os.getpid()) + ' ' + filename)


def daily_report(immediately: bool = False):
    """
    Creates a daily report email around 12:10 UTC or immediately if told to do so
    It also triggers the creation of the daily stats, which will be persisted
    """
    global email_sent

    if conf.send_emails:
        now = datetime.datetime.utcnow()
        if (immediately and datetime.datetime(2012, 1, 17, 12, 20).time() < now.time()) \
                or datetime.datetime(2012, 1, 17, 12, 20).time() > now.time() \
                > datetime.datetime(2012, 1, 17, 12, 10).time() and email_sent != now.day:
            subject = "Daily report for {}".format(conf.bot_instance)
            content = create_mail_content()
            filename_csv = conf.bot_instance + '.csv'
            write_csv(content['csv'], filename_csv)
            send_mail(subject, content['text'], filename_csv)
            email_sent = now.day


def create_mail_content():
    """
    Fetches and formats the data required for the daily report email
    :return: dict: text: str, csv: str
    """
    performance_part = create_report_part_performance()
    advice_part = create_report_part_advice()
    settings_part = create_report_part_settings()
    general_part = create_mail_part_general()

    performance = ["Performance", "-----------", '\n'.join(performance_part['mail']) + '\n* (change within 24 hours, 48 hours)', '\n\n']
    advice = ["Assessment / advice", "-------------------", '\n'.join(advice_part['mail']), '\n\n']
    settings = ["Your settings", "-------------", '\n'.join(settings_part['mail']), '\n\n']
    general = ["General", "-------", '\n'.join(general_part), '\n\n']

    bcs_url = 'https://bitcoin-schweiz.ch/bot/'
    explanation = 'Erläuterungen zu diesem Rapport: https://bitcoin-schweiz.ch/wp-content/uploads/2019/07/Tagesrapport.pdf'
    text = '\n'.join(performance) + '\n'.join(advice) + '\n'.join(settings) + '\n'.join(general) + bcs_url + '\n\n' + explanation + '\n'

    csv = conf.bot_instance + ';' + str(datetime.datetime.utcnow().replace(microsecond=0)) + ' UTC;' + (';'.join(performance_part['csv']) + ';' + ';'.join(
        advice_part['csv']) + ';' + ';'.join(settings_part['csv']) + '\n')

    return {'text': text, 'csv': csv}


def create_report_part_settings():
    return {'mail': ["Rate change: {:>22.1f}%".format(conf.change * 100),
                     "Quota: {:>28}".format('1/' + str(conf.quota)),
                     "Leverage default: {:>17}x".format(str(conf.leverage_default)),
                     "Auto leverage: {:>20}".format(str('Y' if conf.auto_leverage is True else 'N')),
                     "Auto leverage overdrive: {:>10}".format(str('Y' if conf.auto_leverage_overdrive is True else 'N')),
                     "Leverage low: {:>21}x".format(str(conf.leverage_low)),
                     "Leverage high: {:>20}x".format(str(conf.leverage_high)),
                     "Leverage overdrive: {:>15}x".format(str(conf.leverage_high)),
                     "Mayer multiple floor: {:>13}".format(str(conf.mm_floor)),
                     "Mayer multiple ceil: {:>14}".format(str(conf.mm_ceil))],
            'csv': ["Rate change:; {:.1f}%".format(float(conf.change * 100)),
                    "Quota:; {:.3f}".format(1 / conf.quota),
                    "Leverage default:; {}".format(str(conf.leverage_default)),
                    "Auto leverage:; {}".format(str('Y' if conf.auto_leverage is True else 'N')),
                    "Auto leverage overdrive: {}".format(str('Y' if conf.auto_leverage_overdrive is True else 'N')),
                    "Leverage low:; {}".format(str(conf.leverage_low)),
                    "Leverage high:; {}".format(str(conf.leverage_high)),
                    "Leverage overdrive:; {}".format(str(conf.leverage_overdrive)),
                    "Mayer multiple floor:; {}".format(str(conf.mm_floor)),
                    "Mayer multiple ceil:; {}".format(str(conf.mm_ceil))]}


def create_mail_part_general():
    general = ["Generated: {:>28}".format(str(datetime.datetime.utcnow().replace(microsecond=0)) + " UTC")]
    if auto_conf:
        general.append("Resurrected at: {:>18} UTC".format(str(started)))
    else:
        general.append("Running since: {:>20} UTC".format(str(started)))
    general.append("No. of resets: {:>20}".format(reset_counter))
    general.append("Bot: {:>30}".format(conf.bot_instance + '@' + socket.gethostname()))
    general.append("Version: {:>26}".format(conf.bot_version))
    return general


def create_report_part_advice():
    part = {'mail':["Moving average 144d/21d: {:>10}".format('n/a')],
            'csv':["Moving average 144d/21d:; {}".format('n/a')]}
    append_mayer(part)
    return part


def create_report_part_performance():
    part = {'mail': [], 'csv': []}
    balance = get_margin_balance()
    append_performance(part, balance['total'])
    append_balances(part, balance)
    append_orders(part)
    return part


def append_orders(part: dict):
    """
    Appends order statistics
    """
    oos = get_open_orders()
    part['mail'].append("Value of buy orders " + conf.quote + ": {:>10}".format(int(oos.total_buy_order_value)))
    part['mail'].append("Value of sell orders " + conf.quote + ": {:>9}".format(int(oos.total_sell_order_value)))
    part['mail'].append("No. of buy orders: {:>16}".format(len(oos.buy_orders)))
    part['mail'].append("No. of sell orders: {:>15}".format(len(oos.sell_orders)))
    part['csv'].append("Value of buy orders " + conf.quote + ":; {}".format(int(oos.total_buy_order_value)))
    part['csv'].append("Value of sell orders " + conf.quote + ":; {}".format(int(oos.total_sell_order_value)))
    part['csv'].append("No. of buy orders:; {}".format(len(oos.buy_orders)))
    part['csv'].append("No. of sell orders:; {}".format(len(oos.sell_orders)))


def append_balances(part: dict, bal: dict):
    """
    Appends liquidation price, wallet balance, margin balance (including stats), used margin and leverage information
    """
    poi = get_position_info()
    wallet_balance = get_wallet_balance()
    part['mail'].append("Wallet balance " + conf.base + ": {:>18.4f}".format(wallet_balance))
    part['csv'].append("Wallet balance " + conf.base + ":; {:.4f}".format(wallet_balance))
    append_price_and_margin_change(bal['total'], part, conf.base)
    if poi is not None and 'liquidationPrice' in poi:
        part['mail'].append("Liquidation price: {:>16.1f}".format(poi['liquidationPrice']))
        part['csv'].append("Liquidation price:; {:.1f}".format(poi['liquidationPrice']))
    else:
        part['mail'].append("Liquidation price: {:>16}".format('n/a'))
        part['csv'].append("Liquidation price:; {}".format('n/a'))
    used_margin = calculate_used_margin_percentage(bal)
    part['mail'].append("Used margin: {:>22.2f}%".format(used_margin))
    part['csv'].append("Used margin:; {:.2f}%".format(used_margin))
    if conf.exchange == 'kraken':
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>18.2f}%".format(actual_leverage))
        part['csv'].append("Actual leverage:; {:.2f}%".format(actual_leverage))
    elif conf.exchange == 'liquid':
        part['mail'].append("Actual leverage: {:>18}".format('n/a'))
        part['csv'].append("Actual leverage:; {}".format('n/a'))
    else:
        actual_leverage = get_margin_leverage()
        part['mail'].append("Actual leverage: {:>18.2f}x".format(actual_leverage))
        part['csv'].append("Actual leverage:; {:.2f}".format(actual_leverage))
    used_balance = get_used_balance()
    part['mail'].append("Position " + conf.quote + ": {:>21}".format(used_balance))
    part['csv'].append("Position " + conf.quote + ":; {}".format(used_balance))


def append_performance(part: dict, margin_balance: float):
    """
    Calculates and appends the absolute and relative overall performance
    """
    net_deposits = get_net_deposits()
    if net_deposits is None:
        part['mail'].append("Net deposits " + conf.base + ": {:>17}".format('n/a'))
        part['mail'].append("Overall performance in " + conf.base + ": {:>7}".format('n/a'))
        part['csv'].append("Net deposits " + conf.base + ":; {}".format('n/a'))
        part['csv'].append("Overall performance in " + conf.base + ":; {}".format('n/a'))
    else:
        part['mail'].append("Net deposits " + conf.base + ": {:>20.4f}".format(net_deposits))
        part['csv'].append("Net deposits " + conf.base + ":; {:.4f}".format(net_deposits))
        absolute_performance = margin_balance - net_deposits
        if net_deposits > 0:
            relative_performance = round(100 / (net_deposits / absolute_performance), 2)
            part['mail'].append(
                "Overall performance in " + conf.base + ": {:>+10.4f} ({:+.2f}%)".format(absolute_performance,
                                                                                         relative_performance))
            part['csv'].append(
                "Overall performance in " + conf.base + ":; {:.4f} ({:.2f}%)".format(absolute_performance,
                                                                                     relative_performance))
        else:
            part['mail'].append(
                "Overall performance in " + conf.base + ": {:>+10.4f} (% n/a)".format(absolute_performance))
            part['csv'].append(
                "Overall performance in " + conf.base + ":; {:.4f} (% n/a)".format(absolute_performance))


def append_price_and_margin_change(margin_balance: float, part: dict, currency: str):
    """
    Appends price and margin changes
    """
    price = get_current_price()
    today = calculate_daily_statistics(margin_balance, price)

    formatter = 18.4 if currency == conf.base else 16.2
    m_bal = "Margin balance " + currency + ": {:>{}f}".format(today['mBal'], formatter)
    if 'mBalChan24' in today:
        m_bal += " (" if currency == conf.base else "   ("
        m_bal += "{:+.2f}%".format(today['mBalChan24'])
        if 'mBalChan48' in today:
            m_bal += ", {:+.2f}%".format(today['mBalChan48'])
        m_bal += ")*"
    part['mail'].append(m_bal)
    part['csv'].append(m_bal.replace('*', '').replace('  ', '').replace(':', ':;'))

    rate = conf.base + " price " + conf.quote + ": {:>20.1f}".format(price)
    if 'priceChan24' in today:
        rate += "    ("
        rate += "{:+.2f}%".format(today['priceChan24'])
        if 'priceChan48' in today:
            rate += ", {:+.2f}%".format(today['priceChan48'])
        rate += ")*"
    part['mail'].append(rate)
    part['csv'].append(rate.replace('*', '').replace('  ', '').replace(':', ':;'))


def write_csv(csv: str, filename_csv: str):
    if not is_already_written(filename_csv):
        write_mode = 'a' if int(datetime.date.today().strftime("%j")) != 1 else 'w'
        with open(filename_csv, write_mode) as f:
            f.write(csv)


def is_already_written(filename_csv: str):
    if os.path.isfile(filename_csv):
        with open(filename_csv, 'r') as f:
            last_line = list(f)[-1]
            return str(datetime.date.today().isoformat()) in last_line
    return False


def send_mail(subject: str, text: str, filename: str = None):
    recipients = ", ".join(conf.recipient_addresses)
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = conf.sender_address
    msg['To'] = recipients

    readable_part = MIMEMultipart('alternative')
    readable_part.attach(MIMEText(text, 'plain', 'utf-8'))
    html = '<html><body><pre style="font:monospace">' + text + '</pre></body></html>'
    readable_part.attach(MIMEText(html, 'html', 'utf-8'))
    msg.attach(readable_part)

    if filename and os.path.isfile(filename):
        part = MIMEBase('application', 'octet-stream')
        with open(filename, "rb") as f:
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', "attachment; filename={}".format(filename))
        msg.attach(part)

    server = smtplib.SMTP(conf.mail_server, 587)
    server.starttls()
    server.set_debuglevel(0)
    server.login(conf.sender_address, conf.sender_password)
    server.send_message(msg)
    server.quit()
    log.info("Sent email to %s", recipients)


def calculate_daily_statistics(m_bal: float, price: float):
    """
    Calculates, updates and persists the change in the margin balance compared with yesterday
    :param m_bal: todays margin balance
    :param price: the current rate
    :return: todays statistics including price and margin balance changes compared with 24 and 48 hours ago
    """
    global stats

    today = {'mBal': m_bal, 'price': price}
    if stats is None:
        stats = Stats(int(datetime.date.today().strftime("%j")), today)
        persist_statistics()
    else:
        stats.add_day(int(datetime.date.today().strftime("%j")), today)
        persist_statistics()
        before_24h = stats.get_day(int(datetime.date.today().strftime("%j"))-1)
        if before_24h is not None:
            today['mBalChan24'] = round((today['mBal']/before_24h['mBal']-1) * 100, 2)
            if 'price' in before_24h:
                today['priceChan24'] = round((today['price']/before_24h['price']-1) * 100, 2)
            before_48h = stats.get_day(int(datetime.date.today().strftime("%j"))-2)
            if before_48h is not None:
                today['mBalChan48'] = round((today['mBal']/before_48h['mBal']-1) * 100, 2)
                if 'price' in before_48h:
                    today['priceChan48'] = round((today['price']/before_48h['price']-1) * 100, 2)
    return today


def load_statistics():
    content = None
    stats_file = conf.bot_instance + '.pkl'
    if os.path.isfile(stats_file):
        with open(stats_file, "rb") as f:
            content = pickle.load(f)
    return content


def persist_statistics():
    stats_file = conf.bot_instance + '.pkl'
    with open(stats_file, "wb") as f:
        pickle.dump(stats, f)


def fetch_mayer(tries: int = 0):
    try:
        r = requests.get('https://mayermultiple.info/current.json')
        mayer = r.json()['data']
        return {'current': float(mayer['current_mayer_multiple']), 'average': float(mayer['average_mayer_multiple'])}

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ReadTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        if tries < 4:
            return fetch_mayer(tries+1)
        log.warning('Failed to fetch Mayer multiple, giving up after 4 attempts')
        return None


def print_mayer():
    mayer = fetch_mayer()
    if mayer is not None:
        if mayer['current'] < mayer['average']:
            return "Mayer multiple: {:>19.2f} (< {:.2f} = BUY)".format(mayer['current'], mayer['average'])
        if mayer['current'] > 2.4:
            return "Mayer multiple: {:>19.2f} (> 2.4 = SELL)".format(mayer['current'])
        return "Mayer multiple: {:>19.2f} (> {:.2f} and < 2.4 = HOLD)".format(mayer['current'], mayer['average'])
    return


def append_mayer(part: dict):
    text = print_mayer()
    if text is not None:
        part['mail'].append(text)
        part['csv'].append(text.replace('  ', '').replace(':', ':;'))


def boost_leverage():
    if conf.auto_leverage_overdrive:
        if conf.exchange != 'bitmex':
            log.error("boost_leverage() not yet implemented for %s", conf.exchange)
            return
        leverage = get_margin_leverage()
        if leverage < conf.leverage_overdrive:
            log.info('Boosting leverage to {:.1f} (max: {:.1f})'.format(leverage + 0.1, conf.leverage_overdrive))
            set_leverage(leverage + 0.1)


def adjust_leverage():
    if conf.auto_leverage:
        if conf.exchange != 'bitmex':
            log.error("Adjust_leverage() not yet implemented for %s", conf.exchange)
            return
        mm = fetch_mayer()
        leverage = get_margin_leverage()
        if mm is not None and mm['current'] > conf.mm_ceil:
            if leverage > conf.leverage_low:
                set_leverage(leverage - 0.1)
        elif mm is not None and mm['current'] < conf.mm_floor:
            if leverage < conf.leverage_high:
                set_leverage(leverage + 0.1)
        elif mm is not None and mm['current'] < conf.mm_ceil:
            if leverage > conf.leverage_default:
                set_leverage(leverage - 0.1)
            elif leverage < conf.leverage_default:
                set_leverage(leverage + 0.1)


def get_leverage():
    try:
        return float(exchange.private_get_position({'symbol': conf.symbol})[0]['leverage'])

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return get_leverage()


def set_leverage(new_leverage: float):
    try:
        exchange.private_post_position_leverage({'symbol': conf.symbol, 'leverage': new_leverage})

    except (ccxt.ExchangeError, ccxt.AuthenticationError, ccxt.ExchangeNotAvailable, ccxt.RequestTimeout) as error:
        if any(e in str(error.args) for e in no_recall):
            log.warning('Insufficient available balance - not lowering leverage to {:.1f}'.format(new_leverage))
            return
        log.error('Got an error %s %s, retrying in about 5 seconds...', type(error).__name__, str(error.args))
        sleep_for(4, 6)
        return set_leverage(new_leverage)


# ------------------------------------------------------------------------------
if __name__ == '__main__':
    print('Starting Hold n Trade Bot')
    print('ccxt version:', ccxt.__version__)

    if len(sys.argv) > 1:
        filename = os.path.basename(sys.argv[1])
        if len(sys.argv) > 2:
            if sys.argv[2] == '-ac':
                auto_conf = True
            elif sys.argv[2] == '-eo':
                email_only = True
    else:
        filename = os.path.basename(input('Filename with API Keys (config): ') or 'config')

    if not email_only:
        write_control_file(filename)

    log = function_logger(logging.DEBUG, filename, logging.INFO)
    log.info('-------------------------------')
    conf = ExchangeConfig(filename)
    log.info('Holdntrade version: %s', conf.bot_version)
    exchange = connect_to_exchange(conf)
    stats = load_statistics()

    if email_only:
        daily_report(True)
        exit(0)

    loop = init_orders(False, auto_conf)

    while True:
        market_price = get_current_price()
        amount = round(get_balance()['free'] / conf.quota * market_price)

        if loop:
            daily_report()
            buy_executed(market_price, amount)
            sell_executed(market_price, amount)
            if not sell_orders:
                log.info('No sell orders, resetting all orders')
                loop = init_orders(True, False)
            else:
                spread(market_price)

        if not loop:
            compensate()
            loop = True
